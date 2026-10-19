# Fonts

Served from this site, not from a CDN, so the Content-Security-Policy
(`default-src 'self'`) needs no change.

| File | Source (Fontsource, via npm) | SHA-256 |
|---|---|---|
| `plex-sans-400.woff2` | `@fontsource/ibm-plex-sans@5.2.8`, latin, 400 | `3b646991d30055a93a4ecc499713d4347953a74a947ecab435ab72070cbdab0e` |
| `plex-sans-600.woff2` | `@fontsource/ibm-plex-sans@5.2.8`, latin, 600 | `8960851d691c054ed38e259bdcf1a6190d157b4203ed5bb32c632a863fb8ec2f` |
| `plex-mono-400.woff2` | `@fontsource/ibm-plex-mono@5.2.7`, latin, 400 | `08949f728dc52d528e69b1667d15c89a5686a4ee9a296ff90983985f99c380f7` |

IBM Plex is licensed under the SIL Open Font License 1.1 (`OFL.txt`).
Only the Latin subset is included, which covers the product names we use.
To update: download the new files, check the checksums here, and rebuild the image.
