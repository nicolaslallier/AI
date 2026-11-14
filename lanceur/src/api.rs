use std::sync::Arc;

use axum::extract::rejection::JsonRejection;
use axum::extract::{Request, State};
use axum::http::{StatusCode, header::AUTHORIZATION};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use serde_json::json;
use subtle::ConstantTimeEq;

use crate::config::Config;
use crate::conteneurs::{
    DELAI_MAX_S, DemandeLancer, DemandeServices, Erreur, Moteur, espace_valide, valider_services,
};

pub struct Etat<M> {
    pub cfg: Config,
    pub moteur: M,
}

type EtatPartage<M> = State<Arc<Etat<M>>>;
type Corps<T> = Result<Json<T>, JsonRejection>;

#[derive(Deserialize)]
struct DemandeEspace {
    espace: String,
}

pub fn routeur<M: Moteur>(etat: Arc<Etat<M>>) -> Router {
    let protege = Router::new()
        .route("/lancer", post(lancer::<M>))
        .route("/services", post(services::<M>))
        .route("/arreter", post(arreter::<M>))
        .route("/nettoyer", post(nettoyer::<M>))
        .route_layer(middleware::from_fn_with_state(etat.clone(), auth::<M>));
    Router::new()
        .route("/sante", get(|| async { Json(json!({"ok": true})) }))
        .merge(protege)
        .fallback(|| async { erreur(StatusCode::NOT_FOUND, "route inconnue") })
        .with_state(etat)
}

fn erreur(statut: StatusCode, message: impl Into<String>) -> Response {
    (statut, Json(json!({"erreur": message.into()}))).into_response()
}

fn repondre<T: Serialize>(r: Result<T, Erreur>) -> Response {
    match r {
        Ok(v) => Json(v).into_response(),
        Err(Erreur::Refus(m)) => erreur(StatusCode::UNPROCESSABLE_ENTITY, m),
        Err(Erreur::Docker(m)) => erreur(StatusCode::INTERNAL_SERVER_ERROR, m),
    }
}

/// Décode le corps et vérifie l'espace (400 sinon).
fn lire<T>(corps: Corps<T>, espace: impl Fn(&T) -> &str) -> Result<T, (StatusCode, String)> {
    let Json(d) = corps.map_err(|e| (e.status(), e.body_text()))?;
    if !espace_valide(espace(&d)) {
        return Err((StatusCode::BAD_REQUEST, "espace invalide".into()));
    }
    Ok(d)
}

async fn auth<M: Moteur>(State(etat): EtatPartage<M>, req: Request, suivant: Next) -> Response {
    let attendu = format!("Bearer {}", etat.cfg.secret);
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

async fn lancer<M: Moteur>(State(etat): EtatPartage<M>, corps: Corps<DemandeLancer>) -> Response {
    let d = match lire(corps, |d| &d.espace) {
        Ok(d) => d,
        Err((statut, m)) => return erreur(statut, m),
    };
    if d.delai_s == 0 || d.delai_s > DELAI_MAX_S {
        return erreur(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!("delai_s doit être entre 1 et {DELAI_MAX_S}"),
        );
    }
    // Tâche à part : si le client coupe, le conteneur est quand même tué et supprimé.
    match tokio::spawn(async move { etat.moteur.lancer(&etat.cfg, &d).await }).await {
        Ok(r) => repondre(r),
        Err(_) => erreur(StatusCode::INTERNAL_SERVER_ERROR, "exécution interrompue"),
    }
}

async fn services<M: Moteur>(
    State(etat): EtatPartage<M>,
    corps: Corps<DemandeServices>,
) -> Response {
    let d = match lire(corps, |d| &d.espace) {
        Ok(d) => d,
        Err((statut, m)) => return erreur(statut, m),
    };
    if let Err(m) = valider_services(&etat.cfg, &d) {
        return erreur(StatusCode::UNPROCESSABLE_ENTITY, m);
    }
    repondre(
        etat.moteur
            .services(&etat.cfg, &d)
            .await
            .map(|()| json!({"ok": true})),
    )
}

async fn arreter<M: Moteur>(State(etat): EtatPartage<M>, corps: Corps<DemandeEspace>) -> Response {
    match lire(corps, |d| &d.espace) {
        Ok(d) => repondre(
            etat.moteur
                .arreter(&d.espace)
                .await
                .map(|()| json!({"ok": true})),
        ),
        Err((statut, m)) => erreur(statut, m),
    }
}

async fn nettoyer<M: Moteur>(State(etat): EtatPartage<M>, corps: Corps<DemandeEspace>) -> Response {
    match lire(corps, |d| &d.espace) {
        Ok(d) => repondre(
            etat.moteur
                .nettoyer(&d.espace)
                .await
                .map(|()| json!({"ok": true})),
        ),
        Err((statut, m)) => erreur(statut, m),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::config_test;
    use crate::conteneurs::{DemandeLancer, DemandeServices, Erreur, Resultat};
    use axum::body::{Body, to_bytes};
    use axum::http::{Request, StatusCode};
    use serde_json::{Value, json};
    use tower::ServiceExt;

    struct Faux;

    impl Moteur for Faux {
        async fn lancer(&self, _: &Config, _: &DemandeLancer) -> Result<Resultat, Erreur> {
            Ok(Resultat {
                code: Some(0),
                sortie: "ok".into(),
                delai_depasse: false,
            })
        }
        async fn services(&self, _: &Config, _: &DemandeServices) -> Result<(), Erreur> {
            Ok(())
        }
        async fn arreter(&self, _: &str) -> Result<(), Erreur> {
            Ok(())
        }
        async fn nettoyer(&self, _: &str) -> Result<(), Erreur> {
            Ok(())
        }
    }

    async fn appel(
        methode: &str,
        chemin: &str,
        secret: Option<&str>,
        corps: Value,
    ) -> (StatusCode, Value) {
        let app = routeur(Arc::new(Etat {
            cfg: config_test(),
            moteur: Faux,
        }));
        let mut req = Request::builder()
            .method(methode)
            .uri(chemin)
            .header("content-type", "application/json");
        if let Some(s) = secret {
            req = req.header("authorization", format!("Bearer {s}"));
        }
        let rep = app
            .oneshot(req.body(Body::from(corps.to_string())).unwrap())
            .await
            .unwrap();
        let statut = rep.status();
        let octets = to_bytes(rep.into_body(), usize::MAX).await.unwrap();
        (
            statut,
            serde_json::from_slice(&octets).unwrap_or(Value::Null),
        )
    }

    fn lancer(espace: &str, delai_s: u64) -> Value {
        json!({"espace": espace, "image": "ghcr.io/x/execution:1", "commande": "pytest",
               "delai_s": delai_s, "lecture_seule": []})
    }

    fn bon() -> String {
        "s".repeat(32)
    }

    #[tokio::test]
    async fn auth() {
        let (s, _) = appel("POST", "/lancer", None, lancer("tache-1-1", 10)).await;
        assert_eq!(s, StatusCode::UNAUTHORIZED);
        let (s, _) = appel("POST", "/lancer", Some("mauvais"), lancer("tache-1-1", 10)).await;
        assert_eq!(s, StatusCode::UNAUTHORIZED);
        let (s, _) = appel("POST", "/arreter", None, json!({"espace": "tache-1-1"})).await;
        assert_eq!(s, StatusCode::UNAUTHORIZED);
        let (s, v) = appel("GET", "/sante", None, Value::Null).await;
        assert_eq!((s, v), (StatusCode::OK, json!({"ok": true})));
        let (s, v) = appel("POST", "/lancer", Some(&bon()), lancer("tache-1-1", 10)).await;
        assert_eq!(s, StatusCode::OK);
        assert_eq!(
            v,
            json!({"code": 0, "sortie": "ok", "delai_depasse": false})
        );
    }

    #[tokio::test]
    async fn espace_invalide_400() {
        for e in ["../x", "Tache-1", ""] {
            let (s, v) = appel("POST", "/lancer", Some(&bon()), lancer(e, 10)).await;
            assert_eq!(s, StatusCode::BAD_REQUEST, "{e:?}");
            assert!(v["erreur"].is_string());
        }
        let (s, _) = appel("POST", "/nettoyer", Some(&bon()), json!({"espace": "a/b"})).await;
        assert_eq!(s, StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn delai_trop_long_422() {
        let (s, v) = appel("POST", "/lancer", Some(&bon()), lancer("tache-1-1", 1801)).await;
        assert_eq!(s, StatusCode::UNPROCESSABLE_ENTITY);
        assert!(v["erreur"].is_string());
        let (s, _) = appel("POST", "/lancer", Some(&bon()), lancer("tache-1-1", 1800)).await;
        assert_eq!(s, StatusCode::OK);
    }

    #[tokio::test]
    async fn services_valides() {
        let svc = |nom: &str, image: &str| json!({"espace": "tache-1-1", "services": [{"nom": nom, "image": image, "env": {"A": "1"}}]});
        let (s, _) = appel(
            "POST",
            "/services",
            Some(&bon()),
            svc("db", "postgres:16-alpine"),
        )
        .await;
        assert_eq!(s, StatusCode::OK);
        let (s, _) = appel("POST", "/services", Some(&bon()), svc("db", "redis:7")).await;
        assert_eq!(s, StatusCode::UNPROCESSABLE_ENTITY);
        let (s, _) = appel(
            "POST",
            "/services",
            Some(&bon()),
            svc("Db_1", "postgres:16-alpine"),
        )
        .await;
        assert_eq!(s, StatusCode::UNPROCESSABLE_ENTITY);
    }
}
