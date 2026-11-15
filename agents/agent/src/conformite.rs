//! Suite de conformité au contrat `v1` : un agent sur mesure la passe s'il respecte le contrat.
//!
//! Elle vérifie le contrat, pas le raisonnement. Un faux portail scripté sert le modèle et les
//! outils ; l'agent tourne derrière `serveur::routeur`, comme en conteneur.

use std::future::Future;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use axum::extract::State;
use axum::http::{HeaderMap, StatusCode, header::AUTHORIZATION};
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use axum::{Json, Router};
use serde_json::{Value, json};

use crate::serveur::{Tourner, routeur};

const SECRET: &str = "secret-de-conformite-0123456789abcdef";
const JETON: &str = "jeton-de-conformite";
const DELAI_LENT: Duration = Duration::from_millis(200);

#[derive(Clone, Copy, PartialEq)]
enum Mode {
    Normal,
    /// Le modèle répond 429 à tout appel.
    Refus,
    /// Le modèle met du temps à répondre (pour couper pendant l'appel).
    Lent,
}

struct Faux {
    mode: Mode,
    appels: AtomicU64,
    sans_jeton: AtomicU64,
}

impl Faux {
    /// Compte l'appel ; `Some(401)` si le jeton de la mission manque.
    fn recevoir(&self, h: &HeaderMap) -> Option<Response> {
        self.appels.fetch_add(1, Ordering::SeqCst);
        let attendu = format!("Bearer {JETON}");
        if h.get(AUTHORIZATION).map(|v| v.as_bytes()) == Some(attendu.as_bytes()) {
            return None;
        }
        self.sans_jeton.fetch_add(1, Ordering::SeqCst);
        Some(
            (
                StatusCode::UNAUTHORIZED,
                Json(json!({"erreur": "jeton invalide"})),
            )
                .into_response(),
        )
    }
}

async fn modele(State(f): State<Arc<Faux>>, h: HeaderMap, Json(d): Json<Value>) -> Response {
    if let Some(r) = f.recevoir(&h) {
        return r;
    }
    match f.mode {
        Mode::Refus => {
            return (
                StatusCode::TOO_MANY_REQUESTS,
                Json(json!({"erreur": "limite"})),
            )
                .into_response();
        }
        Mode::Lent => tokio::time::sleep(DELAI_LENT).await,
        Mode::Normal => {}
    }
    if d["flux"] == true {
        let corps = concat!(
            "{\"type\":\"texte\",\"texte\":\"un\"}\n",
            "{\"type\":\"texte\",\"texte\":\" deux\"}\n",
            "{\"type\":\"fin\",\"message\":{\"role\":\"assistant\",\"content\":\"un deux\"}}\n"
        );
        return ([("content-type", "application/x-ndjson")], corps).into_response();
    }
    // Un tour d'outil vers le premier outil offert, puis une réponse texte.
    let deja_un_resultat = d["messages"]
        .as_array()
        .is_some_and(|m| m.iter().any(|m| m["role"] == "tool"));
    let message = if d["outils"] == true && !deja_un_resultat {
        json!({"role": "assistant", "content": null, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "lire", "arguments": "{\"chemin\": \"README.md\"}"}}
        ]})
    } else {
        json!({"role": "assistant", "content": "réponse"})
    };
    Json(json!({"message": message})).into_response()
}

async fn outil(State(f): State<Arc<Faux>>, h: HeaderMap) -> Response {
    match f.recevoir(&h) {
        Some(r) => r,
        None => Json(json!({"resultat": "contenu", "arret": false})).into_response(),
    }
}

struct Banc {
    nom: &'static str,
    agent: String,
    faux: Arc<Faux>,
}

async fn servir(app: Router) -> String {
    let ecoute = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("port local");
    let url = format!("http://{}", ecoute.local_addr().expect("adresse"));
    tokio::spawn(async move { axum::serve(ecoute, app).await });
    url
}

async fn banc(nom: &'static str, tourner: Tourner, mode: Mode) -> Banc {
    let faux = Arc::new(Faux {
        mode,
        appels: AtomicU64::new(0),
        sans_jeton: AtomicU64::new(0),
    });
    let portail = Router::new()
        .route("/interne/modele", post(modele))
        .route("/interne/outils", post(outil))
        .with_state(faux.clone());
    let portail_url = servir(portail).await;
    let app = routeur(
        nom,
        SECRET.into(),
        "conformite".into(),
        portail_url,
        tourner,
    );
    Banc {
        nom,
        agent: servir(app).await,
        faux,
    }
}

fn mission(agent: &str, outils: bool, flux: bool) -> Value {
    let schema = json!({"type": "function", "function": {
        "name": "lire", "description": "Lit un fichier.",
        "parameters": {"type": "object", "properties": {"chemin": {"type": "string"}}}}});
    json!({
        "contrat": "v1", "mission": "m-conformite", "agent": agent, "jeton": JETON,
        "messages": [{"role": "user", "content": "Bonjour"}],
        "outils": if outils { vec![schema] } else { vec![] },
        "parametres": {"modele": "m", "temperature": null, "contexte_max": 32000,
                       "tours_max": 5, "produit": "texte", "role": null},
        "response_format": null, "flux": flux
    })
}

impl Banc {
    fn requete(&self, secret: &str, corps: &Value) -> reqwest::RequestBuilder {
        reqwest::Client::new()
            .post(format!("{}/missions", self.agent))
            .bearer_auth(secret)
            .json(corps)
    }

    /// Lit toute la mission : lignes NDJSON complètes, une seule ligne finale, flux terminé.
    async fn lignes(&self, corps: &Value) -> Vec<Value> {
        let r = self.requete(SECRET, corps).send().await.expect("réponse");
        assert_eq!(r.status(), 200, "statut de la mission");
        let texte = tokio::time::timeout(Duration::from_secs(10), r.text())
            .await
            .expect("le flux doit se terminer")
            .expect("corps lisible");
        assert!(
            texte.ends_with('\n'),
            "chaque ligne finit par un saut de ligne"
        );
        let lignes: Vec<Value> = texte
            .lines()
            .map(|l| serde_json::from_str(l).expect("ligne JSON complète"))
            .collect();
        let finales = lignes
            .iter()
            .filter(|l| matches!(l["type"].as_str(), Some("fin" | "erreur")))
            .count();
        assert_eq!(finales, 1, "exactement une ligne fin ou erreur");
        let derniere = lignes.last().expect("au moins une ligne");
        assert!(matches!(derniere["type"].as_str(), Some("fin" | "erreur")));
        assert!(
            lignes[..lignes.len() - 1]
                .iter()
                .all(|l| l["type"] == "texte"),
            "avant la fin, seulement des lignes texte"
        );
        lignes
    }
}

async fn cas_sante(b: Banc) {
    let v: Value = reqwest::get(format!("{}/sante", b.agent))
        .await
        .expect("réponse")
        .json()
        .await
        .expect("JSON");
    assert_eq!(v["contrat"], "v1");
    assert_eq!(v["agent"], b.nom);
}

async fn cas_secret(b: Banc) {
    let r = b
        .requete("mauvais-secret", &mission(b.nom, false, false))
        .send()
        .await
        .expect("réponse");
    assert_eq!(r.status(), 401);
}

async fn cas_autre_agent(b: Banc) {
    let r = b
        .requete(SECRET, &mission("agent-inconnu", false, false))
        .send()
        .await
        .expect("réponse");
    assert_eq!(r.status(), 403);
}

async fn cas_mission_sans_outils(b: Banc) {
    b.lignes(&mission(b.nom, false, false)).await;
}

async fn cas_mission_avec_outils(b: Banc) {
    b.lignes(&mission(b.nom, true, false)).await;
}

async fn cas_jeton(b: Banc) {
    b.lignes(&mission(b.nom, true, false)).await;
    assert!(
        b.faux.appels.load(Ordering::SeqCst) >= 1,
        "aucun appel au portail"
    );
    assert_eq!(
        b.faux.sans_jeton.load(Ordering::SeqCst),
        0,
        "appel sans le jeton de la mission"
    );
}

async fn cas_refus_respecte(b: Banc) {
    b.lignes(&mission(b.nom, true, false)).await;
    assert_eq!(
        b.faux.appels.load(Ordering::SeqCst),
        1,
        "après un refus 429, l'agent ne demande plus rien"
    );
}

async fn cas_annulation(b: Banc) {
    let r = b
        .requete(SECRET, &mission(b.nom, true, false))
        .send()
        .await
        .expect("réponse");
    for _ in 0..250 {
        if b.faux.appels.load(Ordering::SeqCst) >= 1 {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert_eq!(
        b.faux.appels.load(Ordering::SeqCst),
        1,
        "l'appel au modèle n'est pas arrivé"
    );
    drop(r); // la connexion est coupée pendant l'appel au modèle
    tokio::time::sleep(DELAI_LENT * 4).await;
    assert_eq!(
        b.faux.appels.load(Ordering::SeqCst),
        1,
        "aucun appel au portail après l'annulation"
    );
}

async fn cas_flux(b: Banc) {
    let lignes = b.lignes(&mission(b.nom, false, true)).await;
    assert!(lignes.len() >= 2, "au moins une ligne texte avant la fin");
    assert_eq!(lignes[0]["type"], "texte");
}

/// Joue un cas dans une tâche à part ; une panique est rendue avec le nom du cas.
async fn jouer<F, Fut>(nom: &'static str, tourner: Tourner, mode: Mode, cas: &'static str, f: F)
where
    F: FnOnce(Banc) -> Fut,
    Fut: Future<Output = ()> + Send + 'static,
{
    let b = banc(nom, tourner, mode).await;
    if tokio::spawn(f(b)).await.is_err() {
        panic!("conformité : le cas « {cas} » échoue pour l'agent « {nom} »");
    }
}

/// Fait passer la suite à un agent ; panique avec le nom du cas en échec.
pub async fn verifier(nom: &'static str, tourner: Tourner) {
    use Mode::{Lent, Normal, Refus};
    jouer(nom, tourner, Normal, "cas_sante", cas_sante).await;
    jouer(nom, tourner, Normal, "cas_secret", cas_secret).await;
    jouer(nom, tourner, Normal, "cas_autre_agent", cas_autre_agent).await;
    jouer(
        nom,
        tourner,
        Normal,
        "cas_mission_sans_outils",
        cas_mission_sans_outils,
    )
    .await;
    jouer(
        nom,
        tourner,
        Normal,
        "cas_mission_avec_outils",
        cas_mission_avec_outils,
    )
    .await;
    jouer(nom, tourner, Normal, "cas_jeton", cas_jeton).await;
    jouer(
        nom,
        tourner,
        Refus,
        "cas_refus_respecte",
        cas_refus_respecte,
    )
    .await;
    jouer(nom, tourner, Lent, "cas_annulation", cas_annulation).await;
    jouer(nom, tourner, Normal, "cas_flux", cas_flux).await;
}
