//! Boucle par défaut d'un agent : celle de `boucle_outils` (backend/portail/boucle.py), côté agent.
//!
//! L'agent ne décide de rien que le portail impose : ni modèle, ni température, ni outils
//! offerts. Les limites (tours, appels, contexte) sont aussi comptées par le portail.

use futures_util::future::BoxFuture;
use serde_json::{Value, json};

use crate::contrat::{DemandeModele, MessageLlm, Mission};
use crate::portail::{ErreurPortail, Portail};
use crate::serveur::{Fin, Sortie};

const LIMITE: &str =
    "Limite d'outils atteinte : conclus maintenant avec ce que tu as, sans appeler d'outil.";
const IGNORE: &str = "ignoré : une action attend la confirmation de Nicolas";
/// Bornes du portail (`missions.AppelOutil`) : au-delà, le rejeu serait refusé en 422.
const ID_MAX: usize = 200;
const NOM_MAX: usize = 128;
const RESULTAT_RETIRE: &str = "[résultat retiré : relire si besoin]";

pub fn par_defaut(m: Mission, p: Portail, s: Sortie) -> BoxFuture<'static, Result<Fin, String>> {
    Box::pin(async move { executer(m, p, s).await })
}

/// Le texte rendu à l'appelant dit seulement ce que le portail a vu, jamais un contenu.
fn refus(e: ErreurPortail) -> String {
    match e {
        ErreurPortail::Arret => crate::serveur::MISSION_ARRETEE.into(),
        ErreurPortail::Refus { statut, .. } => format!("le portail a refusé l'appel ({statut})"),
        ErreurPortail::Reseau => "portail injoignable".into(),
    }
}

fn contenu(message: &MessageLlm) -> String {
    message.content.clone().unwrap_or_default()
}

async fn appeler(
    p: &Portail,
    messages: &[MessageLlm],
    outils: bool,
    response_format: Option<Value>,
) -> Result<MessageLlm, String> {
    let d = DemandeModele {
        messages: messages.to_vec(),
        outils,
        response_format,
        flux: false,
    };
    p.modele(&d).await.map_err(refus)
}

async fn executer(m: Mission, p: Portail, s: Sortie) -> Result<Fin, String> {
    let mut messages = m.messages;
    if m.outils.is_empty() {
        let reponse = if m.flux {
            p.modele_en_flux(&messages, &s).await.map_err(refus)?
        } else {
            appeler(&p, &messages, false, m.response_format).await?
        };
        let texte = contenu(&reponse);
        messages.push(reponse);
        return Ok(Fin {
            texte,
            messages,
            limite_atteinte: false,
        });
    }
    let offerts: Vec<&str> = m
        .outils
        .iter()
        .filter_map(|o| o["function"]["name"].as_str())
        .collect();
    let mut ids: Vec<String> = Vec::new();
    for _ in 0..m.parametres.tours_max {
        elaguer(&mut messages, m.parametres.contexte_max);
        let reponse = appeler(&p, &messages, true, None).await?;
        let appels = match reponse.tool_calls.clone() {
            Some(a) if !a.is_empty() => a,
            _ => {
                let texte = contenu(&reponse);
                messages.push(reponse);
                return Ok(Fin {
                    texte,
                    messages,
                    limite_atteinte: false,
                });
            }
        };
        // Message rejouable tel quel : ids uniques, arguments en chaîne, un appel par entrée.
        let mut normalises = Vec::new();
        for appel in &appels {
            let mut id = appel["id"]
                .as_str()
                .filter(|i| !i.is_empty() && i.chars().count() <= ID_MAX)
                .map(String::from);
            if id.as_ref().is_none_or(|i| ids.contains(i)) {
                let mut neuf = format!("appel_{}", ids.len());
                while ids.contains(&neuf) {
                    neuf.push('_');
                }
                id = Some(neuf);
            }
            let id = id.expect("id fixé ci-dessus");
            ids.push(id.clone());
            let nom = appel["function"]["name"]
                .as_str()
                .map(|n| n.chars().take(NOM_MAX).collect::<String>());
            let arguments = match &appel["function"]["arguments"] {
                Value::String(a) => Some(a.clone()),
                Value::Object(_) => Some(appel["function"]["arguments"].to_string()),
                Value::Null => Some(String::new()),
                _ => None, // ni chaîne ni objet : appel mal formé
            };
            normalises.push((id, nom, arguments));
        }
        messages.push(MessageLlm {
            role: "assistant".into(),
            content: reponse.content,
            tool_calls: Some(
                normalises
                    .iter()
                    .map(|(id, nom, arguments)| {
                        json!({
                            "id": id,
                            "type": "function",
                            "function": {
                                "name": nom.as_deref().unwrap_or("inconnu"),
                                "arguments": arguments.as_deref().unwrap_or(""),
                            },
                        })
                    })
                    .collect::<Vec<_>>(),
            ),
            ..MessageLlm::default()
        });
        let mut arret = false;
        for (id, nom, arguments) in normalises {
            let resultat = match (&nom, &arguments) {
                _ if arret => IGNORE.to_string(),
                (Some(n), _) if !offerts.contains(&n.as_str()) => {
                    format!("erreur : outil non autorisé : {n}")
                }
                (Some(n), Some(a)) => {
                    let r = p.outil(n, a).await.map_err(refus)?;
                    arret = r.arret;
                    r.resultat
                }
                _ => "erreur : appel d'outil mal formé".to_string(),
            };
            messages.push(MessageLlm {
                role: "tool".into(),
                tool_call_id: Some(id),
                content: Some(resultat),
                ..MessageLlm::default()
            });
        }
        if arret {
            // une action est proposée : le modèle conclut sans outils, Nicolas décide
            elaguer(&mut messages, m.parametres.contexte_max);
            return conclure(&p, messages, false).await;
        }
    }
    messages.push(MessageLlm::nouveau("user", LIMITE));
    elaguer(&mut messages, m.parametres.contexte_max);
    conclure(&p, messages, true).await
}

async fn conclure(p: &Portail, mut messages: Vec<MessageLlm>, limite: bool) -> Result<Fin, String> {
    let reponse = appeler(p, &messages, false, None).await?;
    let texte = contenu(&reponse);
    messages.push(reponse);
    Ok(Fin {
        texte,
        messages,
        limite_atteinte: limite,
    })
}

/// Même estimation que `missions._jetons` : le message entier (`tool_calls` compris), pas
/// `content` seul — un agent qui écrit de gros fichiers remplit son contexte par les arguments.
fn estimer(messages: &[MessageLlm]) -> u64 {
    messages
        .iter()
        .map(|m| {
            let json = serde_json::to_string(m).unwrap_or_default();
            json.chars().count() as u64 / 4 + 4
        })
        .sum()
}

/// Remplace les résultats d'outils et les arguments des appels, du plus ancien au plus récent,
/// de 0,90 à 0,75 du contexte (même règle que `contexte.elaguer_resultats_outils`, étendue aux
/// arguments, que le portail compte aussi). Rend le nombre de messages allégés.
pub fn elaguer(messages: &mut [MessageLlm], contexte_max: u64) -> usize {
    let max = contexte_max as f64;
    if (estimer(messages) as f64) < 0.90 * max {
        return 0;
    }
    let mut n = 0;
    for i in 0..messages.len() {
        if (estimer(messages) as f64) < 0.75 * max {
            break;
        }
        if messages[i].role == "tool" && messages[i].content.as_deref() != Some(RESULTAT_RETIRE) {
            messages[i].content = Some(RESULTAT_RETIRE.into());
            n += 1;
        }
        let mut allege = false;
        for appel in messages[i].tool_calls.iter_mut().flatten() {
            if appel["function"]["arguments"] != "{}" {
                appel["function"]["arguments"] = "{}".into(); // JSON valide, id et nom conservés
                allege = true;
            }
        }
        n += usize::from(allege);
    }
    n
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::serveur::canal;
    use axum::extract::State;
    use axum::routing::post;
    use axum::{Json, Router};
    use std::collections::VecDeque;
    use std::sync::{Arc, Mutex};

    #[derive(Default)]
    struct Faux {
        reponses: Mutex<VecDeque<Value>>,
        demandes: Mutex<Vec<Value>>,
        arret: bool,
    }

    /// Faux portail : le modèle rend les réponses scriptées, l'outil rend « res ».
    async fn demarrer(reponses: Vec<Value>, arret: bool) -> (Portail, Arc<Faux>) {
        let faux = Arc::new(Faux {
            reponses: Mutex::new(reponses.into()),
            arret,
            ..Faux::default()
        });
        let app = Router::new()
            .route(
                "/interne/modele",
                post(
                    |State(f): State<Arc<Faux>>, Json(d): Json<Value>| async move {
                        f.demandes.lock().unwrap().push(d);
                        let message = f
                            .reponses
                            .lock()
                            .unwrap()
                            .pop_front()
                            .expect("réponse scriptée");
                        Json(json!({"message": message}))
                    },
                ),
            )
            .route(
                "/interne/outils",
                post(|State(f): State<Arc<Faux>>| async move {
                    Json(json!({"resultat": "res", "arret": f.arret}))
                }),
            )
            .with_state(faux.clone());
        let ecoute = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", ecoute.local_addr().unwrap());
        tokio::spawn(async move { axum::serve(ecoute, app).await.unwrap() });
        (Portail::new(&url, "j"), faux)
    }

    fn mission(outils: bool, tours_max: u64, flux: bool) -> Mission {
        let schema = json!({"type": "function", "function": {"name": "lire", "parameters": {}}});
        serde_json::from_value(json!({
            "contrat": "v1", "mission": "m", "agent": "a", "jeton": "j",
            "messages": [{"role": "user", "content": "go"}],
            "outils": if outils { vec![schema] } else { vec![] },
            "parametres": {"modele": "m", "temperature": null, "contexte_max": 100000,
                           "tours_max": tours_max, "produit": "p", "role": null},
            "response_format": {"type": "json_object"}, "flux": flux
        }))
        .unwrap()
    }

    fn texte(t: &str) -> Value {
        json!({"role": "assistant", "content": t})
    }

    fn appel(id: Option<&str>, args: Value) -> Value {
        let mut a = json!({"type": "function", "function": {"name": "lire", "arguments": args}});
        if let Some(id) = id {
            a["id"] = id.into();
        }
        a
    }

    fn avec_appels(appels: Vec<Value>) -> Value {
        json!({"role": "assistant", "content": null, "tool_calls": appels})
    }

    #[tokio::test]
    async fn boucle_sans_outils() {
        let (p, faux) = demarrer(vec![texte("bonjour")], false).await;
        let (s, _rx) = canal();
        let fin = par_defaut(mission(false, 3, false), p, s).await.unwrap();
        assert_eq!(fin.texte, "bonjour");
        assert!(!fin.limite_atteinte);
        assert_eq!(fin.messages.len(), 2);
        let d = faux.demandes.lock().unwrap();
        assert_eq!(d.len(), 1);
        assert_eq!(d[0]["outils"], false);
        assert_eq!(d[0]["response_format"], json!({"type": "json_object"}));
        assert_eq!(d[0]["flux"], false);
        // l'agent ne choisit ni modèle, ni température, ni outils
        let mut cles: Vec<_> = d[0].as_object().unwrap().keys().cloned().collect();
        cles.sort();
        assert_eq!(cles, ["flux", "messages", "outils", "response_format"]);
    }

    #[tokio::test]
    async fn boucle_avec_outils_rejouable() {
        let (p, faux) = demarrer(
            vec![
                avec_appels(vec![
                    appel(Some("x"), json!({"chemin": "a"})),
                    appel(Some("x"), json!("{\"chemin\":\"b\"}")),
                ]),
                texte("fini"),
            ],
            false,
        )
        .await;
        let (s, _rx) = canal();
        let fin = par_defaut(mission(true, 5, false), p, s).await.unwrap();
        assert_eq!(fin.texte, "fini");
        assert!(!fin.limite_atteinte);
        let m = &fin.messages;
        // user, assistant (2 appels), 2 résultats, assistant final
        assert_eq!(m.len(), 5);
        let calls = m[1].tool_calls.as_ref().unwrap();
        assert_eq!(calls[0]["id"], "x");
        assert_eq!(calls[1]["id"], "appel_1");
        assert_eq!(calls[0]["function"]["arguments"], "{\"chemin\":\"a\"}");
        assert_eq!(calls[1]["function"]["arguments"], "{\"chemin\":\"b\"}");
        assert_eq!(m[2].role, "tool");
        assert_eq!(m[2].tool_call_id.as_deref(), Some("x"));
        assert_eq!(m[2].content.as_deref(), Some("res"));
        assert_eq!(m[3].tool_call_id.as_deref(), Some("appel_1"));
        let d = faux.demandes.lock().unwrap();
        assert!(d.iter().all(|d| d["outils"] == true));
    }

    #[tokio::test]
    async fn boucle_limite_tours() {
        let tour = || avec_appels(vec![appel(None, json!({}))]);
        let (p, faux) = demarrer(vec![tour(), tour(), texte("bilan")], false).await;
        let (s, _rx) = canal();
        let fin = par_defaut(mission(true, 2, false), p, s).await.unwrap();
        assert_eq!(fin.texte, "bilan");
        assert!(fin.limite_atteinte);
        let d = faux.demandes.lock().unwrap();
        let drapeaux: Vec<_> = d.iter().map(|d| d["outils"].as_bool().unwrap()).collect();
        assert_eq!(drapeaux, [true, true, false]);
        assert_eq!(
            d[2]["messages"].as_array().unwrap().last().unwrap()["content"],
            LIMITE
        );
    }

    #[tokio::test]
    async fn boucle_arret() {
        let (p, faux) = demarrer(
            vec![
                avec_appels(vec![
                    appel(Some("a"), json!({})),
                    appel(Some("b"), json!({})),
                ]),
                texte("proposition"),
            ],
            true,
        )
        .await;
        let (s, _rx) = canal();
        let fin = par_defaut(mission(true, 5, false), p.clone(), s)
            .await
            .unwrap();
        assert_eq!(fin.texte, "proposition");
        assert!(!fin.limite_atteinte);
        assert_eq!(fin.messages[3].content.as_deref(), Some(IGNORE)); // second appel du tour ignoré
        assert_eq!(p.appels(), (2, 1));
        let d = faux.demandes.lock().unwrap();
        assert_eq!(d[1]["outils"], false);
    }

    #[tokio::test]
    async fn boucle_en_flux_sans_outils() {
        let app = Router::new().route(
            "/interne/modele",
            post(|| async {
                concat!(
                    "{\"type\":\"texte\",\"texte\":\"a\"}\n",
                    "{\"type\":\"fin\",\"message\":{\"role\":\"assistant\",\"content\":\"a\"}}\n"
                )
            }),
        );
        let ecoute = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", ecoute.local_addr().unwrap());
        tokio::spawn(async move { axum::serve(ecoute, app).await.unwrap() });
        let (s, mut rx) = canal();
        let fin = par_defaut(mission(false, 3, true), Portail::new(&url, "j"), s)
            .await
            .unwrap();
        assert_eq!(fin.texte, "a");
        assert!(matches!(
            rx.recv().await,
            Some(crate::contrat::Ligne::Texte { .. })
        ));
    }

    #[tokio::test]
    async fn refus_du_portail_en_erreur_au_texte_fixe() {
        let ecoute = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", ecoute.local_addr().unwrap());
        drop(ecoute);
        let (s, _rx) = canal();
        let e = par_defaut(mission(false, 3, false), Portail::new(&url, "j"), s)
            .await
            .err()
            .unwrap();
        assert_eq!(e, "portail injoignable");
    }

    async fn servir_app(app: Router) -> String {
        let ecoute = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", ecoute.local_addr().unwrap());
        tokio::spawn(async move { axum::serve(ecoute, app).await.unwrap() });
        url
    }

    fn conflit() -> (axum::http::StatusCode, Json<Value>) {
        (
            axum::http::StatusCode::CONFLICT,
            Json(json!({"erreur": "mission arrêtée"})),
        )
    }

    #[tokio::test]
    async fn arret_du_portail_sur_le_modele() {
        let app = Router::new().route("/interne/modele", post(|| async { conflit() }));
        let p = Portail::new(&servir_app(app).await, "j");
        let (s, _rx) = canal();
        let e = par_defaut(mission(true, 5, false), p.clone(), s)
            .await
            .err()
            .unwrap();
        assert_eq!(e, crate::serveur::MISSION_ARRETEE);
        assert_eq!(p.appels(), (1, 0)); // aucun nouvel appel
    }

    #[tokio::test]
    async fn arret_du_portail_sur_un_outil() {
        let app = Router::new()
            .route(
                "/interne/modele",
                post(|| async {
                    Json(json!({"message": avec_appels(vec![appel(Some("a"), json!({}))])}))
                }),
            )
            .route("/interne/outils", post(|| async { conflit() }));
        let p = Portail::new(&servir_app(app).await, "j");
        let (s, _rx) = canal();
        let e = par_defaut(mission(true, 5, false), p.clone(), s)
            .await
            .err()
            .unwrap();
        assert_eq!(e, crate::serveur::MISSION_ARRETEE);
        assert_eq!(p.appels(), (1, 1));
    }

    fn outil_msg(c: &str) -> MessageLlm {
        MessageLlm {
            tool_call_id: Some("1".into()),
            ..MessageLlm::nouveau("tool", c)
        }
    }

    #[test]
    fn elaguer_comme_le_portail() {
        // mêmes cas que test_elagage / test_elagage_sous_le_seuil de backend/tests/test_boucle.py
        let gros = "x".repeat(1200);
        let mut messages = vec![
            MessageLlm::nouveau("system", "s"),
            MessageLlm::nouveau("user", "u"),
            outil_msg(&gros),
            outil_msg(&gros),
            outil_msg(&gros),
        ];
        assert_eq!(elaguer(&mut messages, 1000), 1);
        assert_eq!(messages[2].content.as_deref(), Some(RESULTAT_RETIRE));
        assert_eq!(messages[0].content.as_deref(), Some("s"));
        assert_eq!(messages[1].content.as_deref(), Some("u"));
        assert_eq!(messages[3].content.as_deref(), Some(gros.as_str())); // arrêt dès sous 0,75
        assert_eq!(messages[4].content.as_deref(), Some(gros.as_str()));

        // ~800 jetons : dans la bande 0,75-0,90, rien ne doit être retiré
        let mut messages = vec![outil_msg(&"x".repeat(3190))];
        assert!((750..900).contains(&estimer(&messages)));
        assert_eq!(elaguer(&mut messages, 1000), 0);
        assert_eq!(messages[0].content, Some("x".repeat(3190)));
    }

    #[test]
    fn estimer_compte_le_message_entier() {
        // comme `missions._jetons` : le JSON du message, `tool_calls` compris
        let m = MessageLlm {
            role: "assistant".into(),
            tool_calls: Some(vec![appel(Some("a"), json!("x".repeat(4000)))]),
            ..MessageLlm::default()
        };
        assert!(estimer(&[m]) >= 1000);
    }

    #[test]
    fn elaguer_retire_aussi_les_arguments_des_anciens_appels() {
        let ecrire = |id: &str| MessageLlm {
            role: "assistant".into(),
            tool_calls: Some(vec![appel(Some(id), json!("x".repeat(2000)))]),
            ..MessageLlm::default()
        };
        let mut messages = vec![ecrire("a"), outil_msg("ok"), ecrire("b")];
        assert_eq!(elaguer(&mut messages, 1000), 1);
        let args =
            |m: &MessageLlm| m.tool_calls.as_ref().unwrap()[0]["function"]["arguments"].clone();
        assert_eq!(args(&messages[0]), "{}"); // JSON valide, id conservé
        assert_eq!(messages[0].tool_calls.as_ref().unwrap()[0]["id"], "a");
        assert_eq!(args(&messages[2]).as_str().unwrap().len(), 2000);
    }

    #[tokio::test]
    async fn nom_et_id_trop_longs_sont_bornes_a_la_relecture() {
        let mut a = appel(Some(&"i".repeat(201)), json!({}));
        a["function"]["name"] = "n".repeat(129).into();
        let (p, _) = demarrer(vec![avec_appels(vec![a]), texte("fini")], false).await;
        let (s, _rx) = canal();
        let fin = par_defaut(mission(true, 5, false), p, s).await.unwrap();
        let call = &fin.messages[1].tool_calls.as_ref().unwrap()[0];
        assert_eq!(call["id"], "appel_0");
        assert_eq!(call["function"]["name"].as_str().unwrap().len(), 128);
        assert!(
            fin.messages[2]
                .content
                .as_deref()
                .unwrap()
                .starts_with("erreur : outil non autorisé")
        );
    }
}
