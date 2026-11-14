//! Tests contre un vrai Docker : `cargo test -- --ignored`.
//! Chaque test crée son volume et son réseau `internal`, et les supprime.

use std::collections::HashMap;
use std::panic::AssertUnwindSafe;
use std::time::{Duration, Instant};

use bollard::Docker;
use bollard::models::{ContainerCreateBody, HostConfig, NetworkCreateRequest};
use bollard::query_parameters::{
    CreateImageOptions, ListContainersOptions, RemoveContainerOptions, RemoveVolumeOptions,
};
use futures_util::{FutureExt, StreamExt};
use lanceur::config::Config;
use lanceur::conteneurs::{DemandeLancer, Moteur, Resultat};

const IMAGE: &str = "busybox:1.36";

struct Banc {
    docker: Docker,
    cfg: Config,
    espace: String,
}

impl Banc {
    async fn lancer(&self, commande: &str, delai_s: u64, lecture_seule: &[&str]) -> Resultat {
        let d = DemandeLancer {
            espace: self.espace.clone(),
            image: IMAGE.into(),
            commande: commande.into(),
            delai_s,
            lecture_seule: lecture_seule.iter().map(|c| c.to_string()).collect(),
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
            images_services: vec![],
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
async fn utilisateur_non_root() {
    avec_banc("uid", async |b: &Banc| {
        let r = b.lancer("id -u", 30, &[]).await;
        assert_eq!((r.code, r.sortie.trim()), (Some(0), "1000"));
    })
    .await;
}
