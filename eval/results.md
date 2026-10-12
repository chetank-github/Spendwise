# Receipt reader benchmark

- Provider: `groq`, model: `qwen/qwen3.8-27b`
- Receipts: 12 (failed AI calls: 0)
- **Field accuracy: 95.0%**, receipts fully correct: 75.0%
- Latency: median 18.7s, max 49.5s

| Field | Accuracy |
|---|---|
| vendor | 100.0% |
| expense_date | 100.0% |
| total_amount | 100.0% |
| tax_amount | 91.7% |
| gstin | 83.3% |

| Receipt | vendor | expense_date | total_amount | tax_amount | gstin |
|---|---|---|---|---|---|
| r01_restaurant.png | ✅ | ✅ | ✅ | ✅ | ✅ |
| r02_cafe.png | ✅ | ✅ | ✅ | ✅ | ✅ |
| r03_cab.png | ✅ | ✅ | ✅ | ❌ | ✅ |
| r04_hotel.png | ✅ | ✅ | ✅ | ✅ | ✅ |
| r05_software.png | ✅ | ✅ | ✅ | ✅ | ❌ |
| r06_stationery.png | ✅ | ✅ | ✅ | ✅ | ✅ |
| r07_fuel.png | ✅ | ✅ | ✅ | ✅ | ✅ |
| r08_flight.png | ✅ | ✅ | ✅ | ✅ | ❌ |
| r09_lunch.png | ✅ | ✅ | ✅ | ✅ | ✅ |
| r10_training.png | ✅ | ✅ | ✅ | ✅ | ✅ |
| r11_snacks.png | ✅ | ✅ | ✅ | ✅ | ✅ |
| r12_client.png | ✅ | ✅ | ✅ | ✅ | ✅ |