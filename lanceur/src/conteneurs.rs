use std::collections::HashMap;
use std::future::Future;

use std::time::Duration;

use bollard::Docker;
use bollard::errors::Error as ErreurBollard;
use bollard::models::{
    ContainerCreateBody, EndpointSettings, HostConfig, Mount, MountType, MountVolumeOptions,
    NetworkCreateRequest, NetworkingConfig,
};
use bollard::query_parameters::{
    CreateContainerOptions, CreateImageOptions, ListContainersOptions, LogsOptions,
    RemoveContainerOptions,
};
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};

use crate::config::Config;

pub const DELAI_MAX_S: u64 = 1800;

#[derive(Deserialize)]
pub struct DemandeLancer {
    pub espace: String,
    pub image: String,
    pub commande: String,
    #[serde(default = "delai_defaut")]
    pub delai_s: u64,
    #[serde(default)]
    pub lecture_seule: Vec<String>,
}

fn delai_defaut() -> u64 {
    600
}

#[derive(Serialize, Debug)]
pub struct Resultat {
    pub code: Option<i64>,
    pub sortie: String,
    pub delai_depasse: bool,
}

#[derive(Deserialize)]
pub struct Service {
    pub nom: String,
    pub image: String,
    #[serde(default)]
    pub env: HashMap<String, String>,
}

#[derive(Deserialize)]
pub struct DemandeServices {
    pub espace: String,
    pub services: Vec<Service>,
}

#[derive(Debug)]
pub enum Erreur {
    /// Demande refusée (422).
    Refus(String),
    /// Échec côté Docker (500).
    Docker(String),
}

/// Ce que le lanceur demande à Docker ; simulé dans les tests du routeur.
pub trait Moteur: Send + Sync + 'static {
    fn lancer(
        &self,
        cfg: &Config,
        d: &DemandeLancer,
    ) -> impl Future<Output = Result<Resultat, Erreur>> + Send;
    fn services(
        &self,
        cfg: &Config,
        d: &DemandeServices,
    ) -> impl Future<Output = Result<(), Erreur>> + Send;
    fn arreter(&self, espace: &str) -> impl Future<Output = Result<(), Erreur>> + Send;
    fn nettoyer(&self, espace: &str) -> impl Future<Output = Result<(), Erreur>> + Send;
}

const LABEL: &str = "portail.espace";
const SORTIE_MAX: usize = 20_000;

fn nom_valide(s: &str, max: usize) -> bool {
    !s.is_empty()
        && s.len() <= max
        && s.bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

/// `^[a-z0-9-]{1,64}$`
pub fn espace_valide(e: &str) -> bool {
    nom_valide(e, 64)
}

pub fn reseau_services(espace: &str) -> String {
    format!("portail-svc-{espace}")
}

pub fn valider_services(cfg: &Config, d: &DemandeServices) -> Result<(), String> {
    for s in &d.services {
        if !nom_valide(&s.nom, 32) {
            return Err(format!("nom de service invalide : {}", s.nom));
        }
        if !cfg.images_services.contains(&s.image) {
            return Err(format!("image de service non permise : {}", s.image));
        }
        if s.env.keys().any(|k| k.is_empty() || k.contains('=')) {
            return Err(format!("variable invalide pour le service {}", s.nom));
        }
    }
    Ok(())
}

/// Chemin relatif sans `.`, `..`, `.git` ni composant vide, en `[A-Za-z0-9._/-]`.
pub fn chemin_relatif_sur(c: &str) -> bool {
    !c.is_empty()
        && c.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._/-".contains(&b))
        && c.split('/').all(|p| !matches!(p, "" | "." | ".." | ".git"))
}

fn libelle(espace: &str) -> HashMap<String, String> {
    HashMap::from([(LABEL.to_string(), espace.to_string())])
}

/// Spécification d'un conteneur de commande durci. Pure : aucune requête Docker.
pub fn specification(
    cfg: &Config,
    espace: &str,
    image: &str,
    commande: &str,
    lecture_seule: &[String],
    reseau_services: Option<&str>,
) -> Result<ContainerCreateBody, String> {
    if !espace_valide(espace) {
        return Err(format!("espace invalide : {espace}"));
    }
    if !cfg.images.iter().any(|i| i == image) {
        return Err(format!("image non permise : {image}"));
    }
    if let Some(c) = lecture_seule.iter().find(|c| !chemin_relatif_sur(c)) {
        return Err(format!("chemin en lecture seule refusé : {c}"));
    }
    // Toujours un volume nommé et un sous-chemin : jamais de montage de l'hôte.
    let montage = |sous_chemin: String, cible: String, lecture_seule: bool| Mount {
        typ: Some(MountType::VOLUME),
        source: Some(cfg.volume.clone()),
        target: Some(cible),
        read_only: Some(lecture_seule),
        volume_options: Some(MountVolumeOptions {
            subpath: Some(sous_chemin),
            ..Default::default()
        }),
        ..Default::default()
    };
    let mut montages = vec![
        montage(espace.into(), "/travail".into(), false),
        montage(format!("{espace}/.git"), "/travail/.git".into(), true),
    ];
    montages.extend(
        lecture_seule
            .iter()
            .map(|c| montage(format!("{espace}/{c}"), format!("/travail/{c}"), true)),
    );
    let mut reseaux = HashMap::from([(cfg.reseau.clone(), EndpointSettings::default())]);
    if let Some(r) = reseau_services {
        reseaux.insert(r.to_string(), EndpointSettings::default());
    }
    Ok(ContainerCreateBody {
        image: Some(image.into()),
        cmd: Some(vec!["sh".into(), "-c".into(), commande.into()]),
        user: Some("1000:1000".into()),
        working_dir: Some("/travail".into()),
        env: Some(vec![
            format!("HTTP_PROXY={}", cfg.proxy),
            format!("HTTPS_PROXY={}", cfg.proxy),
            "HOME=/home/agent".into(),
        ]),
        labels: Some(libelle(espace)),
        host_config: Some(HostConfig {
            cap_drop: Some(vec!["ALL".into()]),
            security_opt: Some(vec!["no-new-privileges".into()]),
            privileged: Some(false),
            memory: Some(2 * 1024 * 1024 * 1024),
            nano_cpus: Some(2_000_000_000),
            pids_limit: Some(512),
            network_mode: Some(cfg.reseau.clone()),
            tmpfs: Some(HashMap::from([
                ("/tmp".into(), String::new()),
                ("/home/agent".into(), String::new()),
            ])),
            mounts: Some(montages),
            ..Default::default()
        }),
        networking_config: Some(NetworkingConfig {
            endpoints_config: Some(reseaux),
        }),
        ..Default::default()
    })
}

/// Garde les `SORTIE_MAX` derniers caractères.
fn tronquer(s: &str, deja_coupe: bool) -> String {
    let n = s.chars().count();
    if n <= SORTIE_MAX && !deja_coupe {
        return s.to_string();
    }
    let fin: String = s.chars().skip(n.saturating_sub(SORTIE_MAX)).collect();
    format!("[… début coupé]\n{fin}")
}

impl From<ErreurBollard> for Erreur {
    fn from(e: ErreurBollard) -> Self {
        Erreur::Docker(e.to_string())
    }
}

/// Télécharge l'image si elle est absente. L'appelant a déjà vérifié qu'elle est permise.
async fn assurer_image(docker: &Docker, image: &str) -> Result<(), Erreur> {
    if docker.inspect_image(image).await.is_ok() {
        return Ok(());
    }
    // Sans étiquette, Docker téléchargerait toutes les étiquettes.
    let sans_etiquette =
        !image.contains('@') && !image.rsplit('/').next().unwrap_or("").contains(':');
    let options = CreateImageOptions {
        from_image: Some(image.into()),
        tag: sans_etiquette.then(|| "latest".into()),
        ..Default::default()
    };
    let mut flux = docker.create_image(Some(options), None, None);
    while let Some(r) = flux.next().await {
        r?;
    }
    Ok(())
}

async fn executer(docker: &Docker, id: &str, delai_s: u64) -> Result<Resultat, Erreur> {
    docker.start_container(id, None).await?;
    let attente = async {
        match docker.wait_container(id, None).next().await {
            Some(Ok(r)) => Ok(r.status_code),
            Some(Err(ErreurBollard::DockerContainerWaitError { code, .. })) => Ok(code),
            Some(Err(e)) => Err(Erreur::from(e)),
            None => Err(Erreur::Docker("attente du conteneur interrompue".into())),
        }
    };
    let code = match tokio::time::timeout(Duration::from_secs(delai_s), attente).await {
        Ok(code) => Some(code?),
        Err(_) => {
            // SIGKILL par défaut.
            docker.kill_container(id, None).await.ok();
            None
        }
    };
    let options = LogsOptions {
        stdout: true,
        stderr: true,
        ..Default::default()
    };
    let mut flux = docker.logs(id, Some(options));
    let mut octets = Vec::new();
    let mut coupe = false;
    while let Some(morceau) = flux.next().await {
        octets.extend_from_slice(&morceau?.into_bytes());
        // 4 octets par caractère au plus : on garde de quoi faire SORTIE_MAX caractères.
        if octets.len() > 8 * SORTIE_MAX {
            octets.drain(..octets.len() - 4 * SORTIE_MAX);
            coupe = true;
        }
    }
    let mut sortie = tronquer(&String::from_utf8_lossy(&octets), coupe);
    if code.is_none() {
        sortie.push_str(&format!("\n[délai dépassé : {delai_s} s]"));
    }
    Ok(Resultat {
        code,
        sortie,
        delai_depasse: code.is_none(),
    })
}

fn par_espace(espace: &str, tous: bool) -> ListContainersOptions {
    ListContainersOptions {
        all: tous,
        filters: Some(HashMap::from([(
            "label".to_string(),
            vec![format!("{LABEL}={espace}")],
        )])),
        ..Default::default()
    }
}

fn force() -> Option<RemoveContainerOptions> {
    Some(RemoveContainerOptions {
        force: true,
        ..Default::default()
    })
}

impl Moteur for Docker {
    async fn lancer(&self, cfg: &Config, d: &DemandeLancer) -> Result<Resultat, Erreur> {
        let reseau = reseau_services(&d.espace);
        let reseau = self
            .inspect_network(&reseau, None)
            .await
            .ok()
            .map(|_| reseau);
        let corps = specification(
            cfg,
            &d.espace,
            &d.image,
            &d.commande,
            &d.lecture_seule,
            reseau.as_deref(),
        )
        .map_err(Erreur::Refus)?;
        assurer_image(self, &d.image).await?;
        let id = self.create_container(None, corps).await?.id;
        let resultat = executer(self, &id, d.delai_s).await;
        // Supprimé dans tous les cas.
        let suppression = self.remove_container(&id, force()).await;
        let resultat = resultat?;
        suppression?;
        Ok(resultat)
    }

    async fn services(&self, _cfg: &Config, d: &DemandeServices) -> Result<(), Erreur> {
        let reseau = reseau_services(&d.espace);
        if self.inspect_network(&reseau, None).await.is_err() {
            self.create_network(NetworkCreateRequest {
                name: reseau.clone(),
                internal: Some(true),
                labels: Some(libelle(&d.espace)),
                ..Default::default()
            })
            .await?;
        }
        for s in &d.services {
            assurer_image(self, &s.image).await?;
            let nom = format!("{reseau}-{}", s.nom);
            self.remove_container(&nom, force()).await.ok();
            let corps = ContainerCreateBody {
                image: Some(s.image.clone()),
                env: Some(s.env.iter().map(|(k, v)| format!("{k}={v}")).collect()),
                labels: Some(libelle(&d.espace)),
                host_config: Some(HostConfig {
                    network_mode: Some(reseau.clone()),
                    privileged: Some(false),
                    ..Default::default()
                }),
                networking_config: Some(NetworkingConfig {
                    endpoints_config: Some(HashMap::from([(
                        reseau.clone(),
                        EndpointSettings {
                            aliases: Some(vec![s.nom.clone()]),
                            ..Default::default()
                        },
                    )])),
                }),
                ..Default::default()
            };
            let options = CreateContainerOptions {
                name: Some(nom.clone()),
                ..Default::default()
            };
            self.create_container(Some(options), corps).await?;
            self.start_container(&nom, None).await?;
        }
        Ok(())
    }

    async fn arreter(&self, espace: &str) -> Result<(), Erreur> {
        for c in self
            .list_containers(Some(par_espace(espace, false)))
            .await?
        {
            if let Some(id) = c.id {
                // Peut déjà être arrêté entre-temps.
                self.kill_container(&id, None).await.ok();
            }
        }
        Ok(())
    }

    async fn nettoyer(&self, espace: &str) -> Result<(), Erreur> {
        for c in self.list_containers(Some(par_espace(espace, true))).await? {
            if let Some(id) = c.id {
                deja_parti(self.remove_container(&id, force()).await)?;
            }
        }
        deja_parti(self.remove_network(&reseau_services(espace)).await)
    }
}

/// Absent (404) ou déjà en cours de suppression (409) : rien à faire.
fn deja_parti(r: Result<(), ErreurBollard>) -> Result<(), Erreur> {
    match r {
        Err(ErreurBollard::DockerResponseServerError {
            status_code: 404 | 409,
            ..
        }) => Ok(()),
        r => Ok(r?),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::config_test;

    const IMAGE: &str = "ghcr.io/x/execution:1";
    const ESPACE: &str = "tache-1-1";

    fn spec(ro: &[&str]) -> Result<ContainerCreateBody, String> {
        let ro: Vec<String> = ro.iter().map(|c| c.to_string()).collect();
        specification(&config_test(), ESPACE, IMAGE, "pytest", &ro, None)
    }

    fn montages(c: &ContainerCreateBody) -> &[Mount] {
        c.host_config.as_ref().unwrap().mounts.as_deref().unwrap()
    }

    fn montage<'a>(c: &'a ContainerCreateBody, cible: &str) -> &'a Mount {
        montages(c)
            .iter()
            .find(|m| m.target.as_deref() == Some(cible))
            .unwrap_or_else(|| panic!("aucun montage sur {cible}"))
    }

    fn sous_chemin(m: &Mount) -> Option<&str> {
        m.volume_options.as_ref()?.subpath.as_deref()
    }

    #[test]
    fn image_refusee() {
        let r = specification(&config_test(), ESPACE, "alpine:3", "id", &[], None);
        assert!(r.is_err());
    }

    #[test]
    fn durcissement() {
        let c = spec(&[]).unwrap();
        let h = c.host_config.as_ref().unwrap();
        assert_eq!(c.user.as_deref(), Some("1000:1000"));
        assert_eq!(h.cap_drop, Some(vec!["ALL".to_string()]));
        assert_eq!(h.security_opt, Some(vec!["no-new-privileges".to_string()]));
        assert_eq!(h.privileged, Some(false));
        assert_eq!(h.pids_limit, Some(512));
        assert_eq!(h.memory, Some(2 * 1024 * 1024 * 1024));
        assert_eq!(h.nano_cpus, Some(2_000_000_000));
        assert_eq!(h.network_mode.as_deref(), Some("run-net"));
        assert_eq!(
            c.env,
            Some(vec![
                "HTTP_PROXY=http://run-egress:3128".to_string(),
                "HTTPS_PROXY=http://run-egress:3128".to_string(),
                "HOME=/home/agent".to_string(),
            ])
        );
        let tmpfs = h.tmpfs.as_ref().unwrap();
        assert!(tmpfs.contains_key("/tmp") && tmpfs.contains_key("/home/agent"));
        assert_eq!(c.cmd, Some(vec!["sh".into(), "-c".into(), "pytest".into()]));
        assert_eq!(c.working_dir.as_deref(), Some("/travail"));
        assert_eq!(
            c.labels
                .as_ref()
                .unwrap()
                .get("portail.espace")
                .map(String::as_str),
            Some(ESPACE)
        );
        let travail = montage(&c, "/travail");
        assert_eq!(sous_chemin(travail), Some(ESPACE));
        assert_eq!(travail.read_only, Some(false));
        assert_eq!(montages(&c).len(), 2);
        let reseaux = c.networking_config.unwrap().endpoints_config.unwrap();
        assert_eq!(reseaux.keys().collect::<Vec<_>>(), ["run-net"]);
    }

    #[test]
    fn reseau_de_services_rattache() {
        let c = specification(
            &config_test(),
            ESPACE,
            IMAGE,
            "x",
            &[],
            Some("portail-svc-tache-1-1"),
        )
        .unwrap();
        let reseaux = c.networking_config.unwrap().endpoints_config.unwrap();
        assert_eq!(reseaux.len(), 2);
        assert!(reseaux.contains_key("run-net") && reseaux.contains_key("portail-svc-tache-1-1"));
    }

    #[test]
    fn git_toujours_en_lecture_seule() {
        let c = spec(&[]).unwrap();
        let git = montage(&c, "/travail/.git");
        assert_eq!(sous_chemin(git), Some("tache-1-1/.git"));
        assert_eq!(git.read_only, Some(true));
    }

    #[test]
    fn lecture_seule_ajoutee() {
        let c = spec(&["backend/tests"]).unwrap();
        let m = montage(&c, "/travail/backend/tests");
        assert_eq!(sous_chemin(m), Some("tache-1-1/backend/tests"));
        assert_eq!(m.read_only, Some(true));
        assert_eq!(m.source.as_deref(), Some("portail-espaces"));
    }

    #[test]
    fn lecture_seule_refuse() {
        for c in [
            "../x",
            "/etc",
            "a/../b",
            ".git/hooks",
            "a b",
            "",
            "./a",
            "a//b",
        ] {
            assert!(!chemin_relatif_sur(c), "{c:?} accepté");
            assert!(spec(&[c]).is_err(), "{c:?} accepté par specification");
        }
        assert!(chemin_relatif_sur("backend/tests"));
        assert!(chemin_relatif_sur("a.b/c-d_e"));
    }

    #[test]
    fn aucun_bind() {
        let c = spec(&["tests", "backend/tests"]).unwrap();
        for m in montages(&c) {
            assert_eq!(m.typ, Some(MountType::VOLUME));
            assert!(m.bind_options.is_none());
            assert_eq!(m.source.as_deref(), Some("portail-espaces"));
        }
        assert!(c.host_config.unwrap().binds.is_none());
    }

    #[test]
    fn espaces() {
        assert!(espace_valide("tache-12-3"));
        for e in ["", "Tache", "a/b", "a_b", &"a".repeat(65)] {
            assert!(!espace_valide(e), "{e:?} accepté");
        }
    }

    #[test]
    fn sortie_tronquee() {
        assert_eq!(tronquer("abc", false), "abc");
        let longue = format!("x{}", "é".repeat(20_000));
        let t = tronquer(&longue, false);
        assert_eq!(t, format!("[… début coupé]\n{}", "é".repeat(20_000)));
        assert!(tronquer("abc", true).starts_with("[… début coupé]\n"));
    }
}
