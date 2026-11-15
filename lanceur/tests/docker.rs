//! Tests contre un vrai Docker : `cargo test -- --ignored`.
//! Chaque test crée son volume et son réseau `internal`, et les supprime.

use std::collections::HashMap;
use std::panic::AssertUnwindSafe;
use std::time::{Duration, Instant};

use bollard::Docker;
use bollard::exec::{CreateExecOptions, StartExecResults};
use bollard::models::{ContainerCreateBody, HostConfig, NetworkCreateRequest};
use bollard::query_parameters::{
    CreateImageOptions, ListContainersOptions, RemoveContainerOptions, RemoveVolumeOptions,
};
use futures_util::{FutureExt, StreamExt};
use lanceur::config::Config;
use lanceur::conteneurs::{
    DemandeLancer, DemandeServices, Erreur, Moteur, Resultat, Service, nom_service,
};

const IMAGE: &str = "busybox:1.36";

struct Banc {
    docker: Docker,
    cfg: Config,
    espace: String,
}

impl Banc {
    async fn lancer(&self, commande: &str, delai_s: u64, lecture_seule: &[&str]) -> Resultat {
        self.lancer_avec(commande, delai_s, lecture_seule, false)
            .await
    }

    async fn lancer_avec(
        &self,
        commande: &str,
        delai_s: u64,
        lecture_seule: &[&str],
        tout_lecture_seule: bool,
    ) -> Resultat {
        let d = DemandeLancer {
            espace: self.espace.clone(),
            image: IMAGE.into(),
            commande: commande.into(),
            delai_s,
            lecture_seule: lecture_seule.iter().map(|c| c.to_string()).collect(),
            tout_lecture_seule,
        };
        self.docker.lancer(&self.cfg, &d).await.unwrap()
    }
}

async fn tirer(docker: &Docker) {
    let options = CreateImageOptions {
        from_image: Some(IMAGE.into()),
        ..Default::default()
    };
    let mut flux = docker.create_image(Some(options), None, None);
    while let Some(r) = flux.next().await {
        r.unwrap();
    }
}

/// Prépare un espace `<espace>/` (avec `.git/hooks` et `tests/a.py`) dans un volume neuf,
/// exécute `corps`, puis supprime volume et réseau, même si `corps` panique.
async fn avec_banc<F: AsyncFnOnce(&Banc)>(nom: &str, corps: F) {
    let docker = Docker::connect_with_defaults()
        .unwrap()
        .negotiate_version()
        .await
        .unwrap();
    let suffixe = format!("{}-{nom}", std::process::id());
    let volume = format!("lanceur-test-{suffixe}");
    let reseau = format!("lanceur-test-{suffixe}");
    let espace = format!("t-{suffixe}");
    tirer(&docker).await;
    docker
        .create_volume(bollard::models::VolumeCreateRequest {
            name: Some(volume.clone()),
            ..Default::default()
        })
        .await
        .unwrap();
    docker
        .create_network(NetworkCreateRequest {
            name: reseau.clone(),
            internal: Some(true),
            ..Default::default()
        })
        .await
        .unwrap();
    // Remplissage du volume par un conteneur jetable (montage de volume, pas de l'hôte).
    let preparation = format!(
        "mkdir -p /v/{espace}/.git/hooks /v/{espace}/tests && echo orig > /v/{espace}/tests/a.py \
         && chown -R 1000:1000 /v/{espace}"
    );
    let id = docker
        .create_container(
            None,
            ContainerCreateBody {
                image: Some(IMAGE.into()),
                cmd: Some(vec!["sh".into(), "-c".into(), preparation]),
                host_config: Some(HostConfig {
                    binds: Some(vec![format!("{volume}:/v")]),
                    network_mode: Some("none".into()),
                    ..Default::default()
                }),
                ..Default::default()
            },
        )
        .await
        .unwrap()
        .id;
    docker.start_container(&id, None).await.unwrap();
    let attente = docker.wait_container(&id, None).next().await.unwrap();
    let force = Some(RemoveContainerOptions {
        force: true,
        ..Default::default()
    });
    docker.remove_container(&id, force.clone()).await.unwrap();
    attente.unwrap();

    let banc = Banc {
        cfg: Config {
            secret: "s".repeat(32),
            volume: volume.clone(),
            reseau: reseau.clone(),
            proxy: "http://proxy.invalide:3128".into(),
            images: vec![IMAGE.into()],
            // la liste du lanceur est fermée : le service du test doit y figurer
            images_services: vec!["postgres:16-alpine".into()],
        },
        docker: docker.clone(),
        espace,
    };
    let resultat = AssertUnwindSafe(corps(&banc)).catch_unwind().await;

    // Chaque étape est tentée avant de vérifier quoi que ce soit.
    let nettoyage = docker.nettoyer(&banc.espace).await;
    let reseau_supprime = docker.remove_network(&reseau).await;
    let volume_supprime = docker
        .remove_volume(&volume, None::<RemoveVolumeOptions>)
        .await;
    if let Err(panique) = resultat {
        std::panic::resume_unwind(panique);
    }
    nettoyage.unwrap();
    reseau_supprime.unwrap();
    volume_supprime.unwrap();
}

#[tokio::test]
#[ignore]
async fn ecriture_lecture_seule_echoue() {
    avec_banc("ro", async |b: &Banc| {
        let r = b.lancer("echo x > tests/a.py", 30, &["tests"]).await;
        assert_ne!(r.code, Some(0), "{r:?}");
        let r = b.lancer("cat tests/a.py", 30, &[]).await;
        assert_eq!((r.code, r.sortie.trim()), (Some(0), "orig"));
        // Le reste de l'espace reste modifiable.
        let r = b.lancer("echo x > b.py && cat b.py", 30, &["tests"]).await;
        assert_eq!((r.code, r.sortie.trim()), (Some(0), "x"), "{r:?}");
    })
    .await;
}

#[tokio::test]
#[ignore]
async fn tout_lecture_seule_ecriture_echoue() {
    avec_banc("toutro", async |b: &Banc| {
        let r = b.lancer_avec("touch x", 30, &[], true).await;
        assert_ne!(r.code, Some(0), "{r:?}");
        let r = b.lancer_avec("cat tests/a.py", 30, &[], true).await;
        assert_eq!((r.code, r.sortie.trim()), (Some(0), "orig"), "{r:?}");
    })
    .await;
}

#[tokio::test]
#[ignore]
async fn git_non_modifiable() {
    avec_banc("git", async |b: &Banc| {
        let r = b.lancer("echo x > .git/hooks/pre-commit", 30, &[]).await;
        assert_ne!(r.code, Some(0), "{r:?}");
        let r = b.lancer("test -e .git/hooks/pre-commit", 30, &[]).await;
        assert_ne!(r.code, Some(0), "{r:?}");
    })
    .await;
}

#[tokio::test]
#[ignore]
async fn delai_tue_le_conteneur() {
    avec_banc("delai", async |b: &Banc| {
        let debut = Instant::now();
        let r = b.lancer("echo debut; sleep 30", 2, &[]).await;
        assert!(debut.elapsed() < Duration::from_secs(10));
        assert!(r.delai_depasse);
        assert_eq!(r.code, None);
        assert!(r.sortie.starts_with("debut"), "{r:?}");
        assert!(r.sortie.ends_with("[délai dépassé : 2 s]"), "{r:?}");
        let filtre = HashMap::from([(
            "label".to_string(),
            vec![format!("portail.espace={}", b.espace)],
        )]);
        let restants = b
            .docker
            .list_containers(Some(ListContainersOptions {
                all: true,
                filters: Some(filtre),
                ..Default::default()
            }))
            .await
            .unwrap();
        assert!(restants.is_empty());
    })
    .await;
}

#[tokio::test]
#[ignore]
async fn pas_de_reseau() {
    avec_banc("reseau", async |b: &Banc| {
        let r = b.lancer("wget -T 3 -O - http://1.1.1.1", 30, &[]).await;
        assert_ne!(r.code, Some(0), "{r:?}");
    })
    .await;
}

#[tokio::test]
#[ignore]
async fn sans_route_directe() {
    avec_banc("route", async |b: &Banc| {
        let r = b.lancer("wget -T 3 -q -O- http://1.1.1.1", 30, &[]).await;
        assert_ne!(r.code, Some(0), "{r:?}");
    })
    .await;
}

#[tokio::test]
#[ignore]
async fn utilisateur_non_root() {
    avec_banc("uid", async |b: &Banc| {
        let r = b.lancer("id -u", 30, &[]).await;
        assert_eq!((r.code, r.sortie.trim()), (Some(0), "1000"));
    })
    .await;
}

fn postgres(espace: &str) -> DemandeServices {
    DemandeServices {
        espace: espace.into(),
        services: vec![Service {
            nom: "db".into(),
            image: "postgres:16-alpine".into(),
            env: HashMap::from([("POSTGRES_PASSWORD".into(), "essai".into())]),
        }],
    }
}

/// Code de sortie d'une commande exécutée dans un conteneur.
async fn exec(docker: &Docker, conteneur: &str, cmd: &[&str]) -> Option<i64> {
    let id = docker
        .create_exec(
            conteneur,
            CreateExecOptions {
                cmd: Some(cmd.iter().map(|c| c.to_string()).collect()),
                attach_stdout: Some(true),
                attach_stderr: Some(true),
                ..Default::default()
            },
        )
        .await
        .unwrap()
        .id;
    if let StartExecResults::Attached { mut output, .. } =
        docker.start_exec(&id, None).await.unwrap()
    {
        while output.next().await.is_some() {}
    }
    docker.inspect_exec(&id).await.unwrap().exit_code
}

#[tokio::test]
#[ignore]
async fn service_postgres_demarre() {
    avec_banc("pg", async |b: &Banc| {
        b.docker
            .services(&b.cfg, &postgres(&b.espace))
            .await
            .unwrap();
        let nom = nom_service(&b.espace, "db");
        let debut = Instant::now();
        while exec(&b.docker, &nom, &["pg_isready", "-h", "127.0.0.1"]).await != Some(0) {
            assert!(
                debut.elapsed() < Duration::from_secs(30),
                "postgres non prêt"
            );
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
        tokio::time::sleep(Duration::from_secs(2)).await;
        let etat = b
            .docker
            .inspect_container(&nom, None)
            .await
            .unwrap()
            .state
            .unwrap();
        assert_eq!(etat.running, Some(true));
        // Le service est joint directement, sans le proxy.
        let r = b.lancer("echo \"$NO_PROXY|$no_proxy\"", 30, &[]).await;
        assert_eq!(
            r.sortie.trim(),
            "localhost,127.0.0.1,db|localhost,127.0.0.1,db"
        );
        // Relancer remplace le conteneur du même espace.
        b.docker
            .services(&b.cfg, &postgres(&b.espace))
            .await
            .unwrap();
    })
    .await;
}

#[tokio::test]
#[ignore]
async fn service_d_un_autre_espace_refuse() {
    avec_banc("autre", async |b: &Banc| {
        // Un conteneur portant le nom attendu mais le label d'un autre espace.
        let nom = nom_service(&b.espace, "db");
        b.docker
            .create_container(
                Some(bollard::query_parameters::CreateContainerOptions {
                    name: Some(nom.clone()),
                    ..Default::default()
                }),
                ContainerCreateBody {
                    image: Some(IMAGE.into()),
                    labels: Some(HashMap::from([("portail.espace".into(), "autre".into())])),
                    ..Default::default()
                },
            )
            .await
            .unwrap();
        let r = b.docker.services(&b.cfg, &postgres(&b.espace)).await;
        let toujours_la = b.docker.inspect_container(&nom, None).await.is_ok();
        let force = Some(RemoveContainerOptions {
            force: true,
            ..Default::default()
        });
        b.docker.remove_container(&nom, force).await.unwrap();
        assert!(matches!(r, Err(Erreur::Refus(_))), "{r:?}");
        assert!(toujours_la);
    })
    .await;
}

#[tokio::test]
#[ignore]
async fn image_locale_sans_registre_servie() {
    avec_banc("locale", async |b: &Banc| {
        let locale = format!("lanceur-test-locale:{}", std::process::id());
        let (depot, etiquette) = locale.split_once(':').unwrap();
        b.docker
            .tag_image(
                IMAGE,
                Some(bollard::query_parameters::TagImageOptions {
                    repo: Some(depot.into()),
                    tag: Some(etiquette.into()),
                }),
            )
            .await
            .unwrap();
        let cfg = Config {
            secret: b.cfg.secret.clone(),
            volume: b.cfg.volume.clone(),
            reseau: b.cfg.reseau.clone(),
            proxy: b.cfg.proxy.clone(),
            images: vec![locale.clone()],
            images_services: vec![],
        };
        let d = DemandeLancer {
            espace: b.espace.clone(),
            image: locale.clone(),
            commande: "echo ok".into(),
            delai_s: 30,
            lecture_seule: vec![],
            tout_lecture_seule: false,
        };
        // le tirage échoue (image absente de tout registre) : la copie locale sert
        let r = b.docker.lancer(&cfg, &d).await;
        b.docker
            .remove_image(
                &locale,
                None::<bollard::query_parameters::RemoveImageOptions>,
                None,
            )
            .await
            .unwrap();
        assert_eq!(r.unwrap().sortie.trim(), "ok");
    })
    .await;
}
