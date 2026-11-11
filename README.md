# Nit-Hak Håndballapp – Render gratis DEMO

**Kun testdata.** Denne utgaven har 14 oppdiktede spillere, ingen reelle navn og ingen ekte oppmøtefiler. **Ikke last opp ekte Spond-filer.**

## Publiser uten å kjøpe domene eller hosting

1. Lag en privat GitHub-konto/repository. Last opp **innholdet i denne mappen** (ikke ZIP-filen) til repositoryets rot. Ikke legg inn passord i GitHub.
2. Opprett konto på https://dashboard.render.com/ og koble til GitHub.
3. Velg **New → Blueprint**, velg repositoryet og bekreft `render.yaml`.
4. Når Render spør etter `ADMIN_PASSWORD`, angi et **unikt passord på minst 12 tegn**. Ikke skriv det i kildekoden. `SECRET_KEY` genereres av Render.
5. Deploy. Vent til tjenesten viser **Live**, og åpne adressen Render gir deg (`https://...onrender.com`). Brukernavn: `admin`, passordet du valgte.
6. Test oppmøte, bytteplan og live kamp med de oppdiktede spillerne.

## Viktige begrensninger

- Gratis Render-tjeneste kan gå i dvale og starte på nytt. SQLite ligger i `/tmp` og data kan forsvinne ved restart/redeploy. Ikke egnet til kamper eller ekte bruk.
- Gratisnivå og Blueprint-støtte kan endres hos Render; kontroller at **Free** er valgt før bekreftelse. Ingen domeneinnkjøp nødvendig for test.
- Importknappen finnes i grensesnittet, men **skal ikke brukes med ekte Spond-filer**. Test eventuelt med oppdiktede filer.
- Denne demoen er ikke en sikkerhetsrevidert produksjonsapp. Før ekte bruk kreves vedvarende database, backup, sikkerhetsgjennomgang, personvernvurdering og klubbens godkjenning.
- Appen er ikke publisert av ChatGPT; du må selv opprette GitHub- og Render-konto og starte publiseringen.

## Test lokalt med Docker

`docker build -t nithak-demo .`

`docker run --rm -p 8080:8080 -e DEMO_MODE=1 -e SECRET_KEY=change-this-for-local-demo-only -e ADMIN_PASSWORD=change-this-demo-password nithak-demo`

Åpne http://localhost:8080. **Merk:** `SESSION_COOKIE_SECURE=True` krever HTTPS, så lokal innlogging over HTTP virker ikke uten en lokal HTTPS-proxy. Render har HTTPS automatisk.
