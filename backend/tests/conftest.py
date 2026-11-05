"""Make importing the builder's modules safe in tests.

`main` builds the Weekend Saver services when it is imported. Demo mode keeps that
away from Azure and the user's real data folder, and the throwaway output folder keeps
generated files out of the working tree. Both must be set before the first import.
"""

import os
import tempfile

os.environ.setdefault("WEEKEND_SAVER_DEMO", "1")
# Never a real browser tab, whatever the developer's own environment says
os.environ["WEEKEND_SAVER_OPEN_LINK"] = "0"
# Counts as a configured model; the tests replace every call that would reach it
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://model.invalid/")
os.environ.setdefault("BUILDER_GENERATED_DIR", tempfile.mkdtemp(prefix="builder-generated-"))
