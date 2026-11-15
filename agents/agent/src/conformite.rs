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
    /// Le modèle répond 409 (mission arrêtée) à tout appel.
    Arret,
    /// Le modèle demande un outil, l'outil répond 409.
    ArretOutil,
    /// Le modèle fait écrire de gros fichiers à répétition ; garde 413 comme le portail.
    Gros,
}

/// Contexte de la mission « gros fichiers » (en jetons) et taille d'un fichier écrit.
const CONTEXTE_GROS: usize = 8000;
const FICHIER_GROS: usize = 14_000;

struct Faux {
    mode: Mode,
    appels: AtomicU64,
    sans_jeton: AtomicU64,
    /// Corps ou messages hors contrat reçus (refusés en 422).
    invalides: AtomicU64,
}

const CHAMPS_MODELE: [&str; 4] = ["messages", "outils", "response_format", "flux"];
const CHAMPS_OUTIL: [&str; 2] = ["nom", "arguments"];
const CHAMPS_MESSAGE: [&str; 5] = ["role", "content", "tool_calls", "tool_call_id", "name"];

fn cles_dans(v: &Value, permises: &[&str]) -> bool {
    v.as_object()
        .is_some_and(|o| o.keys().all(|k| permises.contains(&k.as_str())))
}

impl Faux {
    /// Comme le portail (`extra="forbid"`) : 422 sur toute clé hors contrat.
    fn valider(&self, corps: &Value, permises: &[&str]) -> Option<Response> {
        let messages_ok = corps["messages"]
            .as_array()
            .is_none_or(|m| m.iter().all(|m| cles_dans(m, &CHAMPS_MESSAGE)));
        if cles_dans(corps, permises) && messages_ok {
            return None;
        }
        self.invalides.fetch_add(1, Ordering::SeqCst);
        Some(
            (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(json!({"erreur": "demande invalide"})),
            )
                .into_response(),
        )
    }

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
    if let Some(r) = f.valider(&d, &CHAMPS_MODELE) {
        return r;
    }
    match f.mode {
        Mode::Arret => {
            return (
                StatusCode::CONFLICT,
                Json(json!({"erreur": "mission arrêtée"})),
            )
                .into_response();
        }
        Mode::Refus => {
            return (
                StatusCode::TOO_MANY_REQUESTS,
                Json(json!({"erreur": "limite"})),
            )
                .into_response();
        }
        Mode::Lent => tokio::time::sleep(DELAI_LENT).await,
        Mode::Normal | Mode::ArretOutil => {}
        Mode::Gros => {
            // même estimation que `missions._jetons` : le message entier, `tool_calls` compris
            let jetons: usize = d["messages"].as_array().map_or(0, |m| {
                m.iter()
                    .map(|m| m.to_string().chars().count() / 4 + 4)
                    .sum()
            });
            if jetons > CONTEXTE_GROS {
                return (
                    StatusCode::PAYLOAD_TOO_LARGE,
                    Json(json!({"erreur": "contexte dépassé"})),
                )
                    .into_response();
            }
        }
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
    let resultats = d["messages"]
        .as_array()
        .map_or(0, |m| m.iter().filter(|m| m["role"] == "tool").count());
    let message = if f.mode == Mode::Gros && d["outils"] == true && resultats < 8 {
        let contenu = "x".repeat(FICHIER_GROS);
        let args = json!({"chemin": "f.txt", "contenu": contenu}).to_string();
        json!({"role": "assistant", "content": null, "tool_calls": [
            {"id": format!("c{resultats}"), "type": "function",
             "function": {"name": "lire", "arguments": args}}
        ]})
    } else if d["outils"] == true && !deja_un_resultat {
        json!({"role": "assistant", "content": null, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "lire", "arguments": "{\"chemin\": \"README.md\"}"}}
        ]})
    } else {
        json!({"role": "assistant", "content": "réponse"})
    };
    Json(json!({"message": message})).into_response()
}

async fn outil(State(f): State<Arc<Faux>>, h: HeaderMap, Json(d): Json<Value>) -> Response {
    if let Some(r) = f.recevoir(&h) {
        return r;
    }
    if let Some(r) = f.valider(&d, &CHAMPS_OUTIL) {
        return r;
    }
    if f.mode == Mode::ArretOutil {
        return (
            StatusCode::CONFLICT,
            Json(json!({"erreur": "mission arrêtée"})),
        )
            .into_response();
    }
    Json(json!({"resultat": "contenu", "arret": false})).into_response()
}

struct Banc {
    nom: &'static str,
    agent: String,
    #[cfg_attr(not(test), allow(dead_code))]
    portail: String,
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
        invalides: AtomicU64::new(0),
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
        portail_url.clone(),
        tourner,
    );
    Banc {
        nom,
        portail: portail_url,
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

/// Un agent qui écrit de gros fichiers à répétition doit élaguer, pas recevoir un 413.
async fn cas_gros_fichiers(b: Banc) {
    let mut m = mission(b.nom, true, false);
    m["parametres"]["contexte_max"] = CONTEXTE_GROS.into();
    m["parametres"]["tours_max"] = 12.into();
    let lignes = b.lignes(&m).await;
    assert_eq!(
        lignes.last().expect("une ligne")["type"],
        "fin",
        "l'agent a reçu un refus du portail au lieu d'élaguer son contexte"
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
    let faux = b.faux.clone();
    if tokio::spawn(f(b)).await.is_err() {
        panic!("conformité : le cas « {cas} » échoue pour l'agent « {nom} »");
    }
    assert_eq!(
        faux.invalides.load(Ordering::SeqCst),
        0,
        "conformité : le cas « {cas} » a envoyé au portail un corps hors contrat (agent « {nom} »)"
    );
}

/// 409 « mission arrêtée » : fin normale, plus aucun appel au portail.
async fn cas_arret_modele(b: Banc) {
    b.lignes(&mission(b.nom, true, false)).await;
    assert_eq!(
        b.faux.appels.load(Ordering::SeqCst),
        1,
        "appel après un 409 du modèle"
    );
}

async fn cas_arret_outil(b: Banc) {
    b.lignes(&mission(b.nom, true, false)).await;
    assert_eq!(
        b.faux.appels.load(Ordering::SeqCst),
        2,
        "appel après un 409 d'un outil"
    );
}

/// Fait passer la suite à un agent ; panique avec le nom du cas en échec.
pub async fn verifier(nom: &'static str, tourner: Tourner) {
    use Mode::{Arret, ArretOutil, Gros, Lent, Normal, Refus};
    jouer(nom, tourner, Arret, "cas_arret_modele", cas_arret_modele).await;
    jouer(nom, tourner, ArretOutil, "cas_arret_outil", cas_arret_outil).await;
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
    jouer(nom, tourner, Gros, "cas_gros_fichiers", cas_gros_fichiers).await;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn le_faux_portail_refuse_un_corps_hors_contrat() {
        let b = banc("revue", crate::boucle::par_defaut, Mode::Normal).await;
        let client = reqwest::Client::new();
        let envoyer = |chemin: &'static str, corps: Value| {
            client
                .post(format!("{}{chemin}", b.portail))
                .bearer_auth(JETON)
                .json(&corps)
                .send()
        };
        let ok = json!({"messages": [{"role": "user", "content": "x"}]});
        assert_eq!(envoyer("/interne/modele", ok).await.unwrap().status(), 200);
        let avec_modele = json!({"modele": "m", "messages": []});
        let r = envoyer("/interne/modele", avec_modele).await.unwrap();
        assert_eq!(r.status(), 422);
        let message_inconnu = json!({"messages": [{"role": "user", "extra": 1}]});
        let r = envoyer("/interne/modele", message_inconnu).await.unwrap();
        assert_eq!(r.status(), 422);
        let r = envoyer(
            "/interne/outils",
            json!({"nom": "lire", "arguments": "{}", "x": 1}),
        )
        .await
        .unwrap();
        assert_eq!(r.status(), 422);
        assert_eq!(b.faux.invalides.load(Ordering::SeqCst), 3);
    }
}
