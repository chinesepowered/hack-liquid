# Third-party material

| What | Where | License |
|---|---|---|
| `capy_tower/lfm_client.py`, vendored unchanged from the hackathon repo `heath0xFF/cleared-for-takeoff-hackathon` (`skills/iq9-geniex-lfm/scripts/lfm_client.py`) | `capy_tower/lfm_client.py` | MIT, Copyright (c) 2026 On-Device AI Hackathon contributors |
| Capybara photo, "Hydrochoeris hydrochaeris in Brazil in Petrópolis, Rio de Janeiro, Brazil 09" by Wilfredor, Wikimedia Commons. Used as-is (`capybara.jpg`) and as a cut-out sprite (`capybara.png`) | `capy_tower/static/img/` | CC0 1.0 (public domain dedication) |
| LiquidAI `d1-2B` and `LFM3-1.7B-GGUF` (Q4_0) weights | not in this repo; staged on the board from the event USB drive | LFM Open License v1.0 |
| Qualcomm GenieX | installed on the board | Qualcomm's terms |

The MIT license text for the vendored client:

```
MIT License

Copyright (c) 2026 On-Device AI Hackathon contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Preset runway photos (`capy_tower/static/img/presets/`, resized), all from Wikimedia Commons

| File | Source | Author | License |
|---|---|---|---|
| `deer.jpg` | White-tailed Deer - Odocoileus virginianus (51360828067).jpg | GlacierNPS | Public domain |
| `coyote.jpg` | Urban coyote on residential street in Grant Park, Portland, Oregon.jpg | PortlandAppraisalBlog | CC BY-SA 4.0 |
| `goose.jpg` | Canada Goose in Canada's Wonderland.jpg | K2HWY | CC BY 4.0 |
| `dog.jpg` | Golden retriever running on a dirt road.jpg | Valentina Storti | CC BY 2.0 |
| `person.jpg` | Hombre Solo - Calle de Pedro Bosch - Madrid.jpg | Javier Perez Montes | CC BY-SA 4.0 |
| `tug.jpg` | Airport Baggage or Tow Tractor.jpg | Oleg Yunakov | CC BY-SA 4.0 |
| `drone.jpg` | Quadcopter camera drone in flight.jpg | Josh Sorenson | CC0 |
| `cone.jpg` | A toppled orange traffic cone at Huntington station.jpg | Ser Amantio di Nicolao | CC BY-SA 4.0 |

`presets.json` holds d1-2B's answers for each preset, measured on the IQ-9075.
