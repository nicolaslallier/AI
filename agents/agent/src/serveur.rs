//! Serveur de missions : `GET /sante` et `POST /missions` (flux NDJSON), voir le contrat `v1`.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use axum::body::{Body, Bytes};
use axum::extract::{Request, State};
use axum::http::{StatusCode, header::AUTHORIZATION, header::CONTENT_TYPE};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use futures_util::future::BoxFuture;
use serde_json::json;
use subtle::ConstantTimeEq;
use tokio::sync::mpsc;
use tokio::task::AbortHandle;

use crate::contrat::{CONTRAT, Ligne, MessageLlm, Mission, Sante};
use crate::journal;
use crate::portail::Portail;

/// Canal par lequel une mission relaie son texte au portail, ligne par ligne.
pub struct Sortie(mpsc::Sender<Ligne>);

impl Sortie {
    /// Relaie un morceau de texte. Sans effet si la connexion est fermée : la mission est
    /// alors déjà en cours d'annulation.
    pub async fn texte(&self, t: &str) {
        let _ = self.0.send(Ligne::Texte { texte: t.into() }).await;
    }
}

/// Une sortie et le récepteur de ses lignes (tests et boucles hors serveur).
pub fn canal() -> (Sortie, mpsc::Receiver<Ligne>) {
    let (tx, rx) = mpsc::channel(16);
    (Sortie(tx), rx)
}

pub struct Fin {
    pub texte: String,
    pub messages: Vec<MessageLlm>,
    pub limite_atteinte: bool,
}

/// Le travail d'un agent : `Err(texte)` devient la ligne `erreur` (texte à destination du
/// portail, jamais journalisé).
pub type Tourner = fn(Mission, Portail, Sortie) -> BoxFuture<'static, Result<Fin, String>>;

struct Etat {
    nom: &'static str,
    secret: String,
    version: String,
    portail_url: String,
    tourner: Tourner,
}

pub fn routeur(
    nom: &'static str,
    secret: String,
    version: String,
    portail_url: String,
    tourner: Tourner,
) -> Router {
    let etat = Arc::new(Etat {
        nom,
        secret,
        version,
        portail_url,
        tourner,
    });
    let protege = Router::new()
        .route("/missions", post(missions))
        .route_layer(middleware::from_fn_with_state(etat.clone(), auth));
    Router::new()
        .route("/sante", get(sante))
        .merge(protege)
        .with_state(etat)
}

fn erreur(statut: StatusCode, message: &str) -> Response {
    (statut, Json(json!({"erreur": message}))).into_response()
}

async fn sante(State(etat): State<Arc<Etat>>) -> Json<Sante> {
    Json(Sante {
        contrat: CONTRAT.into(),
        agent: etat.nom.into(),
        version: etat.version.clone(),
    })
}

async fn auth(State(etat): State<Arc<Etat>>, req: Request, suivant: Next) -> Response {
    let attendu = format!("Bearer {}", etat.secret);
    let recu = req
        .headers()
        .get(AUTHORIZATION)
        .map(|v| v.as_bytes())
        .unwrap_or_default();
    // Temps constant (seule la longueur peut fuiter).
    if bool::from(recu.ct_eq(attendu.as_bytes())) {
        suivant.run(req).await
    } else {
        erreur(StatusCode::UNAUTHORIZED, "non autorisé")
    }
}

/// Tient la mission : si le flux est lâché avant la fin (connexion fermée), la tâche est
/// abandonnée, donc annulée à son prochain point d'attente.
struct Garde {
    tache: AbortHandle,
    termine: Arc<AtomicBool>,
    agent: &'static str,
    mission: String,
}

impl Drop for Garde {
    fn drop(&mut self) {
        if !self.termine.load(Ordering::SeqCst) {
            journal::info(self.agent, &self.mission, "mission annulée", &[]);
            self.tache.abort();
        }
    }
}

fn octets(l: &Ligne) -> Result<Bytes, std::convert::Infallible> {
    let mut s = serde_json::to_string(l).expect("ligne sérialisable");
    s.push('\n');
    Ok(Bytes::from(s))
}

async fn missions(State(etat): State<Arc<Etat>>, corps: Bytes) -> Response {
    let m: Mission = match serde_json::from_slice(&corps) {
        Ok(m) => m,
        Err(_) => return erreur(StatusCode::UNPROCESSABLE_ENTITY, "mission invalide"),
    };
    if m.contrat != CONTRAT {
        return erreur(StatusCode::UNPROCESSABLE_ENTITY, "contrat inconnu");
    }
    if m.agent != etat.nom {
        return erreur(StatusCode::FORBIDDEN, "mission pour un autre agent");
    }
    let (nom, id) = (etat.nom, m.mission.clone());
    journal::info(nom, &id, "mission reçue", &[]);
    let portail = Portail::new(&etat.portail_url, &m.jeton);
    let suivi = portail.clone();
    let (tx, rx) = mpsc::channel(16);
    let sortie = Sortie(tx.clone());
    let termine = Arc::new(AtomicBool::new(false));
    let fait = termine.clone();
    let id_tache = id.clone();
    let tourner = etat.tourner;
    let tache = tokio::spawn(async move {
        let ligne = match tourner(m, portail, sortie).await {
            Ok(f) => {
                let (modele, outils) = suivi.appels();
                let compteurs = [("appels_modele", modele), ("appels_outils", outils)];
                journal::info(nom, &id_tache, "mission finie", &compteurs);
                Ligne::Fin {
                    texte: f.texte,
                    messages: f.messages,
                    limite_atteinte: f.limite_atteinte,
                }
            }
            Err(e) => {
                journal::erreur(nom, &id_tache, "mission en erreur", &[]);
                Ligne::Erreur { erreur: e }
            }
        };
        fait.store(true, Ordering::SeqCst);
        let _ = tx.send(ligne).await;
    });
    let garde = Garde {
        tache: tache.abort_handle(),
        termine,
        agent: nom,
        mission: id.clone(),
    };
    let flux =
        futures_util::stream::unfold((rx, garde, false), |(mut rx, garde, fini)| async move {
            if fini {
                return None;
            }
            let (ligne, fini) = match rx.recv().await {
                Some(l) => {
                    let derniere = !matches!(l, Ligne::Texte { .. });
                    (l, derniere)
                }
                // tâche disparue sans ligne finale (panique) : on clôt proprement le flux
                None => {
                    journal::erreur(garde.agent, &garde.mission, "mission en erreur", &[]);
                    garde.termine.store(true, Ordering::SeqCst);
                    let l = Ligne::Erreur {
                        erreur: "mission interrompue".into(),
                    };
                    (l, true)
                }
            };
            Some((octets(&ligne), (rx, garde, fini)))
        });
    Response::builder()
        .header(CONTENT_TYPE, "application/x-ndjson")
        .body(Body::from_stream(flux))
        .expect("réponse valide")
}

/// Lance le serveur d'un agent : configuration par l'environnement, port 8080.
pub async fn servir(nom: &'static str, tourner: Tourner) {
    let secret = std::env::var("AGENT_SECRET").unwrap_or_default();
    if secret.chars().count() < 32 {
        eprintln!("AGENT_SECRET absent ou de moins de 32 caractères");
        std::process::exit(1);
    }
    let portail_url =
        std::env::var("AGENT_PORTAIL_URL").unwrap_or_else(|_| "http://portail:8000".into());
    let version = std::env::var("AGENT_VERSION").unwrap_or_else(|_| "inconnue".into());
    let ecoute = tokio::net::TcpListener::bind("0.0.0.0:8080")
        .await
        .expect("port 8080 indisponible");
    axum::serve(ecoute, routeur(nom, secret, version, portail_url, tourner))
        .await
        .expect("serveur arrêté");
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;
    use std::time::Duration;

    const SECRET: &str = "0123456789abcdef0123456789abcdef";

    fn emettre(_: Mission, _: Portail, s: Sortie) -> BoxFuture<'static, Result<Fin, String>> {
        Box::pin(async move {
            s.texte("un").await;
            s.texte("deux").await;
            Ok(Fin {
                texte: "fini".into(),
                messages: vec![MessageLlm::nouveau("assistant", "fini")],
                limite_atteinte: false,
            })
        })
    }

    fn echouer(_: Mission, _: Portail, _: Sortie) -> BoxFuture<'static, Result<Fin, String>> {
        Box::pin(async { Err("raté".into()) })
    }

    static ANNULEE: AtomicBool = AtomicBool::new(false);

    struct PoseAuDrop;
    impl Drop for PoseAuDrop {
        fn drop(&mut self) {
            ANNULEE.store(true, Ordering::SeqCst);
        }
    }

    fn attendre(_: Mission, _: Portail, s: Sortie) -> BoxFuture<'static, Result<Fin, String>> {
        Box::pin(async move {
            let _garde = PoseAuDrop;
            s.texte("début").await;
            std::future::pending::<()>().await;
            unreachable!()
        })
    }

    async fn demarrer(tourner: Tourner) -> String {
        let app = routeur(
            "revue",
            SECRET.into(),
            "0.1.0".into(),
            "http://127.0.0.1:1".into(),
            tourner,
        );
        let ecoute = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", ecoute.local_addr().unwrap());
        tokio::spawn(async move { axum::serve(ecoute, app).await.unwrap() });
        url
    }

    fn mission(agent: &str, contrat: &str) -> String {
        json!({
            "contrat": contrat, "mission": "m-1", "agent": agent, "jeton": "j",
            "messages": [{"role": "user", "content": "x"}], "outils": [],
            "parametres": {"modele": "m", "temperature": null, "contexte_max": 1000,
                           "tours_max": 3, "produit": "p", "role": null},
            "response_format": null, "flux": false
        })
        .to_string()
    }

    fn envoyer(url: &str, secret: &str, corps: String) -> reqwest::RequestBuilder {
        reqwest::Client::new()
            .post(format!("{url}/missions"))
            .bearer_auth(secret)
            .header("content-type", "application/json")
            .body(corps)
    }

    #[tokio::test]
    async fn sante_rend_contrat_et_version() {
        let url = demarrer(emettre).await;
        let v: Value = reqwest::get(format!("{url}/sante"))
            .await
            .unwrap()
            .json()
            .await
            .unwrap();
        assert_eq!(
            v,
            json!({"contrat": "v1", "agent": "revue", "version": "0.1.0"})
        );
    }

    #[tokio::test]
    async fn mauvais_secret_401() {
        let url = demarrer(emettre).await;
        let r = envoyer(&url, "autre", mission("revue", "v1"))
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 401);
        let r = reqwest::Client::new()
            .post(format!("{url}/missions"))
            .body(mission("revue", "v1"))
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 401);
    }

    #[tokio::test]
    async fn autre_agent_403() {
        let url = demarrer(emettre).await;
        let r = envoyer(&url, SECRET, mission("plan", "v1"))
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 403);
    }

    #[tokio::test]
    async fn contrat_inconnu_422() {
        let url = demarrer(emettre).await;
        let r = envoyer(&url, SECRET, mission("revue", "v2"))
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 422);
        let r = envoyer(&url, SECRET, "pas du json".into())
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 422);
    }

    #[tokio::test]
    async fn lignes_ndjson_puis_fin() {
        let url = demarrer(emettre).await;
        let r = envoyer(&url, SECRET, mission("revue", "v1"))
            .send()
            .await
            .unwrap();
        assert_eq!(r.status(), 200);
        assert_eq!(r.headers()["content-type"], "application/x-ndjson");
        let corps = r.text().await.unwrap();
        assert!(corps.ends_with('\n'));
        let lignes: Vec<Value> = corps
            .lines()
            .map(|l| serde_json::from_str(l).expect("ligne JSON complète"))
            .collect();
        let types: Vec<&str> = lignes.iter().map(|l| l["type"].as_str().unwrap()).collect();
        assert_eq!(types, ["texte", "texte", "fin"]);
        assert_eq!(lignes[2]["texte"], "fini");
        assert_eq!(lignes[2]["limite_atteinte"], false);
    }

    #[tokio::test]
    async fn erreur_de_mission_en_ligne_erreur() {
        let url = demarrer(echouer).await;
        let r = envoyer(&url, SECRET, mission("revue", "v1"))
            .send()
            .await
            .unwrap();
        let corps = r.text().await.unwrap();
        assert_eq!(corps, "{\"type\":\"erreur\",\"erreur\":\"raté\"}\n");
    }

    #[tokio::test]
    async fn deconnexion_annule_la_mission() {
        let url = demarrer(attendre).await;
        let mut r = envoyer(&url, SECRET, mission("revue", "v1"))
            .send()
            .await
            .unwrap();
        assert!(r.chunk().await.unwrap().is_some()); // la mission a démarré
        assert!(!ANNULEE.load(Ordering::SeqCst));
        drop(r); // le client coupe
        for _ in 0..100 {
            if ANNULEE.load(Ordering::SeqCst) {
                return;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        panic!("la mission n'a pas été annulée");
    }
}
