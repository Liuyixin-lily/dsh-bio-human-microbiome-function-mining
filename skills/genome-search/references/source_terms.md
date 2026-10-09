# Source vocabulary

The script ships with keyword sets for common biological sources. Users may also supply custom comma-separated terms or a file with one term per line.

## Built-in sets

- **skin**: skin, cutaneous, dermal, epidermal, sebaceous, skin swab, skin scraping, skin biopsy, skin lesion, neck skin, forearm
- **oral**: oral cavity, oral, mouth, saliva, salivary, dental plaque, supragingival, subgingival, gingival, periodontal, tongue, buccal, cheek, dental, tooth, teeth, endodontic, root canal, parotid, dental abscess
- **gut**: feces, faeces, stool, fecal, gut, intestinal, intestine, rectal, colon, cecum
- **respiratory**: nasal, nares, nasopharynx, oropharynx, throat, sputum, lung, bronchial, airway, respiratory tract
- **urogenital**: vaginal, urogenital, urine, urinary, urethral, catheter
- **blood**: blood, bloodstream, bacteremia, septicemia, plasma
- **environment**: soil, sediment, water, marine, freshwater, wastewater, sludge, dust, air, rhizosphere

## Matching rule

The default match is direct metadata matching, not ecological inference. A row is called a direct source match only when the requested term appears in a source-like BioSample field such as `isolation_source`, `body_site`, `tissue`, `host_tissue`, `source_name`, `sample_type`, `environment`, or the Assembly record's isolate metadata.
