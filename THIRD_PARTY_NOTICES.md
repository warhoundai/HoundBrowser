# Third-party notices

HoundBrowser does not vendor source from Playwright or Browser Use. Those repositories were reviewed for presentation and project organization; their content, examples, images, badges, and implementation were not copied.

Runtime dependencies are installed separately and retain their own licenses:

| Dependency | License |
| --- | --- |
| Playwright for Python | Apache-2.0 |
| FastAPI | MIT |
| Starlette | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| HTTPX / HTTPCore | BSD-3-Clause |
| Pydantic / pydantic-core | MIT |
| AnyIO | MIT |
| Chromium | BSD and bundled third-party notices |

The container installs Chromium using Playwright's browser installer. Preserve the installed browser's license and credits files when redistributing an image. Debian and Python components also retain their distribution licenses. The generated dependency inventory in `docs/dependencies.json` records installed package versions and license metadata for this release; it is informational and does not replace upstream terms.
