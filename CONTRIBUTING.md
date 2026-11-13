# Contributing to HoundBrowser

Thank you for helping improve HoundBrowser. Start with an issue that describes a concrete problem, or send a focused pull request with a reproducible fixture.

## Local development

Use Python 3.11+ and Node.js 22+. Create a virtual environment, install `requirements-dev.lock`, then install the package with `pip install -e . --no-deps`. Install Chromium using `python -m playwright install --with-deps chromium`.

Run `pytest`, `node --test sdk/js/*.test.mjs`, and `python -m build`. Changes to network boundaries, credential handling, cancellation, or persistence need tests for both success and denied/error cases. Test only controlled fixtures; never scan customer or third-party sites as part of CI.

## Pull requests

Explain the problem, the resulting behavior, and how you verified it. Keep unrelated formatting and dependency updates separate. Include documentation when configuration or API behavior changes. Do not commit `.env` files, credentials, browser profiles, customer captures, or private infrastructure identifiers.

Keep API keys in transport headers, outside model-visible arguments. Never add a shell or unrestricted filesystem/CDP endpoint to the agent API. Do not silently retry uncertain mutations.

## License and review

By submitting a contribution, you agree to license it under Apache 2.0. No separate CLA is required. Preserve copyright and third-party notices. Reviewers may request a smaller change, a controlled reproduction, or a compatibility note before merging.
