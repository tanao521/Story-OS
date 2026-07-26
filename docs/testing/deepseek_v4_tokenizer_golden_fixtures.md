# DeepSeek Tokenizer Audit Fixtures

These values came from the official-page-linked
`deepseek_v3_tokenizer.zip`, SHA-256
`c954ca6f6e54281d72d3c27e2430cea7663f81292b39982e2f97890c66c302de`,
loaded directly through installed `tokenizers.Tokenizer.from_file`.

They are deterministic Layer-A audit fixtures for that Archive only. They are
not V4 Flash mapping evidence, Chat request counts, or billed-token fixtures.

| Fixture | Token count | Token-id sequence SHA-256 |
| --- | ---: | --- |
| empty text | 0 | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `Hello!` | 2 | `93445f72fbe73c0e8b6798912f700ba13c04e626b50fa5a9e38192362a22e773` |
| Chinese | 2 | `5203045ed8e2b6c46c7827a5714b690544d6f6224ee05f83e610988ed1bdf0b6` |
| English with newline | 8 | `81dc300c487787768fee62ea25f233979ebad9ebfc277ad1264cbfdddea8c7e4` |
| mixed Chinese/English/emoji | 7 | `f232db622c59561edc84c58c82173c53aedcd602320e0ab4fe88781b8e6ce650` |
| JSON text | 13 | `b0efd85936d6f2d167e1f318133abab931de908c7bea8658ffba38ebc759c3ba` |
| long Reader Persona text | 800 | `2482dbaa2e20af41de17f48ef2a19b02fda4228e67b89743f492fa524f2903c5` |

Isolation result:

- exit code 0;
- repeated runs within the process produced identical ids;
- socket/network attempts 0;
- new files 0;
- temporary HOME/cache files 0;
- model-id support: no;
- messages support: no;
- response-format support: no.

No two-message or JSON Output full-request golden value is published because
Layers B/C are unverified. Creating such values would imply unsupported
exactness.

