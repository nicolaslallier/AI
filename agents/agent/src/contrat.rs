//! Types du contrat `v1` (docs/agents-contrat-v1.md). Source de vérité côté portail :
//! `backend/portail/missions.py`. Les messages restent des `Value` : l'agent les rejoue tels quels.

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const CONTRAT: &str = "v1";

/// Un message du modèle : ces champs seulement (le portail refuse tout autre champ). En
/// lecture, les champs inconnus sont ignorés (un champ nouveau facultatif ne change pas `v1`).
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct MessageLlm {
    pub role: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
    /// Appels d'outils du modèle, rejoués tels quels.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_calls: Option<Vec<Value>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_call_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
}

impl MessageLlm {
    pub fn nouveau(role: &str, content: impl Into<String>) -> Self {
        Self {
            role: role.into(),
            content: Some(content.into()),
            ..Self::default()
        }
    }
}

/// Pas de `Debug` : la mission porte le jeton, qui ne doit jamais finir dans un journal.
#[derive(Clone, Serialize, Deserialize)]
pub struct Mission {
    pub contrat: String,
    pub mission: String,
    pub agent: String,
    pub jeton: String,
    pub messages: Vec<MessageLlm>,
    pub outils: Vec<Value>,
    pub parametres: Parametres,
    pub response_format: Option<Value>,
    #[serde(default)]
    pub flux: bool,
}

/// Ce que le portail impose ; l'agent le lit, il n'en décide rien.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Parametres {
    pub modele: String,
    pub temperature: Option<f64>,
    pub contexte_max: u64,
    pub tours_max: u64,
    pub produit: String,
    pub role: Option<String>,
}

/// Une ligne du flux NDJSON de `POST /missions` : la dernière est `fin` ou `erreur`.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum Ligne {
    Texte {
        texte: String,
    },
    Fin {
        texte: String,
        messages: Vec<MessageLlm>,
        limite_atteinte: bool,
    },
    Erreur {
        erreur: String,
    },
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DemandeModele {
    pub messages: Vec<MessageLlm>,
    pub outils: bool,
    pub response_format: Option<Value>,
    pub flux: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ReponseModele {
    pub message: MessageLlm,
}

/// Une ligne de la réponse en flux de `/interne/modele` (`flux: true`).
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum LigneModele {
    Texte { texte: String },
    Fin { message: MessageLlm },
    Erreur { erreur: String },
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DemandeOutil {
    pub nom: String,
    /// JSON en chaîne, comme OpenAI.
    pub arguments: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ReponseOutil {
    pub resultat: String,
    #[serde(default)]
    pub arret: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Sante {
    pub contrat: String,
    pub agent: String,
    pub version: String,
}
