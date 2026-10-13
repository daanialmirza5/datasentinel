# 90-second demo script

Setup (before recording): start the API with the demo workspace and the frontend.

```powershell
cd backend; $env:DATASENTINEL_LOAD_SAMPLES_ON_STARTUP="true"; .\.venv\Scripts\python.exe -m uvicorn datasentinel.main:app --port 8000
cd frontend; npm run dev     # open http://localhost:5173
```

| Time | Screen | Say |
|---|---|---|
| 0:00 | Dashboard | "DataSentinel catches silent data failures before they reach decisions. This is a synthetic shop: orders, customers, products, and the reports and models built on them. Every number here comes from stored validation runs and version comparisons." |
| 0:12 | Dashboard → *Active anomalies* | "September's order export looks fine at a glance, but seven signals fired versus August: missing ship countries jumped from 1 % to 18 %, a JPY currency appeared, 41 amounts are extreme, rows were duplicated, and the `discount` column vanished — probably renamed, which it says is *likely*, not confirmed." |
| 0:28 | Drift monitoring → orders | "Each signal shows its test and effect size, and charts compare the versions. Identifier columns are excluded so a new month of order ids isn't flagged." |
| 0:40 | Lineage → orders → *Trace downstream impact* | "Orders feed a revenue job, daily revenue, an executive dashboard and a forecast model. The job reads orders directly, so it's a *suspected impact*. The dashboard is an *unverified risk*. Dependence isn't proof of corruption, and the labels say so." |
| 0:52 | Recommendations | "Recommendations are rule-based and cite evidence: quarantine version 3 — nothing is deleted — and version 2 becomes current because it passed every rule." |
| 1:02 | Fault lab → orders, base v2, *Numeric outliers*, `amount` | "To prove detection works, I inject a seeded fault into a copy. The detector never sees the ground truth. It's detected, with zero false positives, and the same seed reproduces byte-identical data." |
| 1:18 | Reports → *Generate report* → *Export Markdown* | "And everything exports as a Markdown or JSON report for the team. In a 280-scenario benchmark it detected 96 % of default-intensity faults with no false alarms on 20 healthy controls — on synthetic data, which the docs are explicit about." |
| 1:30 | — | End. |

Numbers quoted are from the demo data and [benchmark](benchmark.md); re-check them if the data or
detectors change.
