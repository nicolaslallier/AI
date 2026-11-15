/// Configuration du lanceur, lue dans l'environnement.
pub struct Config {
    pub secret: String,
    pub volume: String,
    pub reseau: String,
    pub proxy: String,
    pub images: Vec<String>,
    pub images_services: Vec<String>,
}

impl Config {
    pub fn depuis_env() -> Result<Config, String> {
        Self::depuis(|cle| std::env::var(cle).ok())
    }

    pub fn depuis(lire: impl Fn(&str) -> Option<String>) -> Result<Config, String> {
        let lire = |cle: &str| lire(cle).filter(|v| !v.trim().is_empty());
        let secret = lire("LANCEUR_SECRET").unwrap_or_default();
        if secret.chars().count() < 32 {
            return Err("LANCEUR_SECRET doit faire au moins 32 caractères".into());
        }
        let proxy = lire("LANCEUR_PROXY").ok_or("LANCEUR_PROXY manquant")?;
        let liste = |cle: &str| -> Vec<String> {
            lire(cle)
                .unwrap_or_default()
                .split(',')
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .map(String::from)
                .collect()
        };
        Ok(Config {
            secret,
            volume: lire("LANCEUR_VOLUME").unwrap_or_else(|| "portail-espaces".into()),
            reseau: lire("LANCEUR_RESEAU").unwrap_or_else(|| "run-net".into()),
            proxy,
            images: liste("LANCEUR_IMAGES"),
            images_services: liste("LANCEUR_IMAGES_SERVICES"),
        })
    }
}

/// Référence à démarrer pour l'image demandée : l'entrée de la liste égale à la
/// demande, ou dont la partie avant `@` l'est (demande `nom:tag`, liste `nom:tag@sha256:…`).
pub fn epinglee<'a>(liste: &'a [String], demandee: &str) -> Option<&'a str> {
    liste
        .iter()
        .map(String::as_str)
        .find(|e| *e == demandee || e.split_once('@').is_some_and(|(nom, _)| nom == demandee))
}

#[cfg(test)]
pub fn config_test() -> Config {
    Config {
        secret: "s".repeat(32),
        volume: "portail-espaces".into(),
        reseau: "run-net".into(),
        proxy: "http://run-egress:3128".into(),
        images: vec!["ghcr.io/x/execution:1".into()],
        images_services: vec!["postgres:16-alpine".into()],
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn lire(vars: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let vars: HashMap<String, String> = vars
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        move |cle| vars.get(cle).cloned()
    }

    #[test]
    fn secret_trop_court() {
        let court = "a".repeat(31);
        let r = Config::depuis(lire(&[
            ("LANCEUR_SECRET", &court),
            ("LANCEUR_PROXY", "http://p:3128"),
        ]));
        assert!(r.is_err());
        assert!(Config::depuis(lire(&[("LANCEUR_PROXY", "http://p:3128")])).is_err());
    }

    #[test]
    fn valeurs_par_defaut_et_listes() {
        let secret = "a".repeat(32);
        let c = Config::depuis(lire(&[
            ("LANCEUR_SECRET", &secret),
            ("LANCEUR_PROXY", "http://p:3128"),
            ("LANCEUR_IMAGES", "a:1, b:2,"),
        ]))
        .unwrap();
        assert_eq!(c.volume, "portail-espaces");
        assert_eq!(c.reseau, "run-net");
        assert_eq!(c.images, ["a:1", "b:2"]);
        assert!(c.images_services.is_empty());
    }

    #[test]
    fn image_epinglee() {
        let l = vec![
            "postgres:16-alpine@sha256:aaa".to_string(),
            "busybox:1.36".to_string(),
        ];
        assert_eq!(
            epinglee(&l, "postgres:16-alpine"),
            Some("postgres:16-alpine@sha256:aaa")
        );
        assert_eq!(
            epinglee(&l, "postgres:16-alpine@sha256:aaa"),
            Some("postgres:16-alpine@sha256:aaa")
        );
        assert_eq!(epinglee(&l, "busybox:1.36"), Some("busybox:1.36"));
        assert_eq!(epinglee(&l, "postgres:16"), None); // préfixe : refusé
        assert_eq!(epinglee(&l, "postgres:16-alpine@sha256:bbb"), None); // autre digest : refusé
        assert_eq!(epinglee(&l, "busybox:1.36@sha256:ccc"), None);
    }
}
