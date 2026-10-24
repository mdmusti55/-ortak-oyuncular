# Ortak Oyuncular

İki futbol kulübünün Transfermarkt transfer geçmişinde ortak olan oyuncuları bulur ve her kulübe geliş/imza yılını gösterir. Maça çıkma şartı yoktur; transfer geçmişinde kulübün `from` veya `to` tarafında görünmek yeterlidir. Kiralık transferler dahildir.

## Veri

Build sırasında `dcaribou/transfermarkt-datasets` projesinin Cloudflare R2 üzerindeki `clubs.csv.gz` ve `transfers.csv.gz` snapshot'ları indirilir. Snapshot 6 Temmuz 2026'ya kadardır.

## GitHub Pages

Repo `main` branch'ine gönderildiğinde `.github/workflows/pages.yml` veriyi indirir, kompakt kulüp→oyuncu indeksini `index.html` içine gömer ve GitHub Pages'e deploy eder.

Pages ayarlarında **Source = GitHub Actions** olmalıdır. İlk build bittikten sonra site bir HTTPS URL'de açılır. Sonraki kullanımlarda service worker sayesinde ana dosya cache'lenir.

## Yerelde test

```bash
python build.py
python -m http.server 8000 -d dist
```

Sonra `http://localhost:8000`.
