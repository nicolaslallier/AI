//! Client du portail : `/interne/modele` et `/interne/outils`, avec le jeton de la mission.

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use futures_util::StreamExt;
use serde::Serialize;
use serde::de::DeserializeOwned;
use serde_json::Value;

use crate::contrat::{
    DemandeModele, DemandeOutil, LigneModele, MessageLlm, ReponseModele, ReponseOutil,
};
use crate::serveur::Sortie;

#[derive(Debug)]
pub enum ErreurPortail {
    /// Le portail a refusé (401, 409, 413, 422, 429, 502…) : `erreur` est son texte fixe.
    Refus { statut: u16, erreur: String },
    /// Pas de réponse exploitable (connexion, flux coupé, corps illisible).
    Reseau,
}

#[derive(Default)]
struct Compteurs {
    modele: AtomicU64,
    outils: AtomicU64,
}

/// Pas de `Debug` : le jeton ne doit jamais être affiché.
#[derive(Clone)]
pub struct Portail {
    url: String,
    jeton: String,
    client: reqwest::Client,
    compteurs: Arc<Compteurs>,
}

impl Portail {
    pub fn new(url: &str, jeton: &str) -> Self {
        // Pas de délai total : le portail tient la durée de la mission.
        let client = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(10))
            .build()
            .expect("client HTTP");
        Self {
            url: url.trim_end_matches('/').to_string(),
            jeton: jeton.to_string(),
            client,
            compteurs: Arc::default(),
        }
    }

    /// (appels au modèle, appels d'outils) faits par cette mission.
    pub fn appels(&self) -> (u64, u64) {
        (
            self.compteurs.modele.load(Ordering::Relaxed),
            self.compteurs.outils.load(Ordering::Relaxed),
        )
    }

    async fn envoyer<T: Serialize>(
        &self,
        chemin: &str,
        corps: &T,
    ) -> Result<reqwest::Response, ErreurPortail> {
        let r = self
            .client
            .post(format!("{}{chemin}", self.url))
            .bearer_auth(&self.jeton)
            .json(corps)
            .send()
            .await
            .map_err(|_| ErreurPortail::Reseau)?;
        let statut = r.status();
        if statut.is_success() {
            return Ok(r);
        }
        let erreur = r
            .json::<Value>()
            .await
            .ok()
            .and_then(|v| v["erreur"].as_str().map(String::from))
            .unwrap_or_else(|| "refus du portail".into());
        Err(ErreurPortail::Refus {
            statut: statut.as_u16(),
            erreur,
        })
    }

    async fn demander<T: Serialize, R: DeserializeOwned>(
        &self,
        chemin: &str,
        corps: &T,
    ) -> Result<R, ErreurPortail> {
        let r = self.envoyer(chemin, corps).await?;
        r.json().await.map_err(|_| ErreurPortail::Reseau)
    }

    /// Un appel simple au modèle ; rend le `message` de la réponse.
    pub async fn modele(&self, d: &DemandeModele) -> Result<MessageLlm, ErreurPortail> {
        self.compteurs.modele.fetch_add(1, Ordering::Relaxed);
        let r: ReponseModele = self.demander("/interne/modele", d).await?;
        Ok(r.message)
    }

    /// Un appel en flux (sans outils) : chaque ligne `texte` est relayée sur `sortie`.
    pub async fn modele_en_flux(
        &self,
        messages: &[MessageLlm],
        sortie: &Sortie,
    ) -> Result<MessageLlm, ErreurPortail> {
        self.compteurs.modele.fetch_add(1, Ordering::Relaxed);
        let demande = DemandeModele {
            messages: messages.to_vec(),
            outils: false,
            response_format: None,
            flux: true,
        };
        let mut flux = self
            .envoyer("/interne/modele", &demande)
            .await?
            .bytes_stream();
        let mut tampon: Vec<u8> = Vec::new();
        while let Some(morceau) = flux.next().await {
            tampon.extend_from_slice(&morceau.map_err(|_| ErreurPortail::Reseau)?);
            while let Some(i) = tampon.iter().position(|&b| b == b'\n') {
                let brute: Vec<u8> = tampon.drain(..=i).collect();
                if let Some(fin) = traiter_ligne(&brute, sortie).await? {
                    return Ok(fin);
                }
            }
        }
        // dernière ligne sans saut de ligne
        match traiter_ligne(&tampon, sortie).await? {
            Some(fin) => Ok(fin),
            None => Err(ErreurPortail::Reseau),
        }
    }

    pub async fn outil(&self, nom: &str, arguments: &str) -> Result<ReponseOutil, ErreurPortail> {
        self.compteurs.outils.fetch_add(1, Ordering::Relaxed);
        let d = DemandeOutil {
            nom: nom.to_string(),
            arguments: arguments.to_string(),
        };
        self.demander("/interne/outils", &d).await
    }
}

/// `Some(message)` sur la ligne `fin`, `None` pour une ligne vide ou un texte relayé.
async fn traiter_ligne(brute: &[u8], sortie: &Sortie) -> Result<Option<MessageLlm>, ErreurPortail> {
    if brute.iter().all(u8::is_ascii_whitespace) {
        return Ok(None);
    }
    match serde_json::from_slice(brute).map_err(|_| ErreurPortail::Reseau)? {
        LigneModele::Texte { texte } => {
            sortie.texte(&texte).await;
            Ok(None)
        }
        LigneModele::Fin { message } => Ok(Some(message)),
        LigneModele::Erreur { erreur } => Err(ErreurPortail::Refus {
            statut: 502,
            erreur,
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contrat::Ligne;
    use crate::serveur::canal;
    use axum::http::{HeaderMap, StatusCode, header::AUTHORIZATION};
    use axum::response::IntoResponse;
    use axum::routing::post;
    use axum::{Json, Router};
    use serde_json::json;

    const JETON: &str = "jeton-ok";

    async fn servir(app: Router) -> String {
        let ecoute = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", ecoute.local_addr().unwrap());
        tokio::spawn(async move { axum::serve(ecoute, app).await.unwrap() });
        url
    }

    fn jeton_valide(h: &HeaderMap) -> bool {
        h.get(AUTHORIZATION).map(|v| v.as_bytes()) == Some(format!("Bearer {JETON}").as_bytes())
    }

    fn non_autorise() -> axum::response::Response {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({"erreur": "jeton invalide"})),
        )
            .into_response()
    }

    fn demande() -> DemandeModele {
        DemandeModele {
            messages: vec![MessageLlm::nouveau("user", "salut")],
            outils: false,
            response_format: None,
            flux: false,
        }
    }

    fn faux_portail() -> Router {
        Router::new()
            .route(
                "/interne/modele",
                post(|h: HeaderMap| async move {
                    if !jeton_valide(&h) {
                        return non_autorise();
                    }
                    Json(json!({"message": {"role": "assistant", "content": "ok"}})).into_response()
                }),
            )
            .route(
                "/interne/outils",
                post(|h: HeaderMap| async move {
                    if !jeton_valide(&h) {
                        return non_autorise();
                    }
                    Json(json!({"resultat": "r", "arret": false})).into_response()
                }),
            )
    }

    #[tokio::test]
    async fn jeton_sur_chaque_appel() {
        let url = servir(faux_portail()).await;
        let bon = Portail::new(&url, JETON);
        assert_eq!(
            bon.modele(&demande()).await.unwrap().content.as_deref(),
            Some("ok")
        );
        assert_eq!(bon.outil("lire", "{}").await.unwrap().resultat, "r");
        assert_eq!(bon.appels(), (1, 1));

        let mauvais = Portail::new(&url, "autre");
        assert!(matches!(
            mauvais.modele(&demande()).await,
            Err(ErreurPortail::Refus { statut: 401, .. })
        ));
        assert!(matches!(
            mauvais.outil("lire", "{}").await,
            Err(ErreurPortail::Refus { statut: 401, .. })
        ));
    }

    #[tokio::test]
    async fn refus_du_portail_rendu() {
        let app = Router::new().route(
            "/interne/modele",
            post(|| async {
                (
                    StatusCode::TOO_MANY_REQUESTS,
                    Json(json!({"erreur": "limite d'appels"})),
                )
            }),
        );
        let url = servir(app).await;
        match Portail::new(&url, JETON).modele(&demande()).await {
            Err(ErreurPortail::Refus { statut, erreur }) => {
                assert_eq!(statut, 429);
                assert_eq!(erreur, "limite d'appels");
            }
            autre => panic!("refus attendu : {autre:?}"),
        }
    }

    #[tokio::test]
    async fn portail_injoignable_est_un_echec_reseau() {
        let ecoute = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", ecoute.local_addr().unwrap());
        drop(ecoute);
        assert!(matches!(
            Portail::new(&url, JETON).modele(&demande()).await,
            Err(ErreurPortail::Reseau)
        ));
    }

    #[tokio::test]
    async fn flux_relaye_le_texte() {
        let app = Router::new().route(
            "/interne/modele",
            post(|h: HeaderMap| async move {
                if !jeton_valide(&h) {
                    return non_autorise();
                }
                let corps = concat!(
                    "{\"type\":\"texte\",\"texte\":\"Verdict\"}\n",
                    "{\"type\":\"texte\",\"texte\":\" : conforme.\"}\n",
                    "{\"type\":\"fin\",\"message\":{\"role\":\"assistant\",\"content\":\"Verdict : conforme.\"}}"
                );
                ([("content-type", "application/x-ndjson")], corps).into_response()
            }),
        );
        let url = servir(app).await;
        let (sortie, mut rx) = canal();
        let message = Portail::new(&url, JETON)
            .modele_en_flux(&[MessageLlm::nouveau("user", "x")], &sortie)
            .await
            .unwrap();
        assert_eq!(message.content.as_deref(), Some("Verdict : conforme."));
        drop(sortie);
        let mut textes = Vec::new();
        while let Some(Ligne::Texte { texte }) = rx.recv().await {
            textes.push(texte);
        }
        assert_eq!(textes, ["Verdict", " : conforme."]);
    }
}
