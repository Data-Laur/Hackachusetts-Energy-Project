"""
download_data.py — fetch the raw data files for Heat Check.

The three CSVs are NOT stored in this repo (they are large and gitignored). Run
this once to download them from the Building Data Genome Project 2 (BDG2) GitHub
repo into the Datasets/ folder, then run the pipeline.

How to run (from the repo root):
    python scripts/download_data.py

Downloads into Datasets/:
    metadata.csv       (building metadata)
    steam_cleaned.csv  (hourly steam meter readings, wide format)
    weather.csv        (hourly weather per site)

Data source: Building Data Genome Project 2.
  https://github.com/buds-lab/building-data-genome-project-2
  Miller, C., Kathirgamanathan, A., Picchetti, B. et al. Sci Data 7, 368 (2020).
  https://doi.org/10.1038/s41597-020-00712-x

Note: these files are served via Git LFS, so we use the media.githubusercontent
"media" host, which returns the real file contents (not an LFS pointer).
"""

import os
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

# BDG2 stores large files with Git LFS; this host returns the actual bytes.
BASE = (
    "https://media.githubusercontent.com/media/"
    "buds-lab/building-data-genome-project-2/master/data"
)

# Map each local filename to its folder on the BDG2 repo.
FILES = {
    "metadata.csv": f"{BASE}/metadata/metadata.csv",
    "steam_cleaned.csv": f"{BASE}/meters/cleaned/steam_cleaned.csv",
    "weather.csv": f"{BASE}/weather/weather.csv",
}

DEST_DIR = "Datasets"


def _download_urllib(url, dest_path):
    """Download with Python's urllib, showing a simple progress line."""
    def report(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(100, downloaded * 100 // total_size)
            mb = downloaded / 1_000_000
            sys.stdout.write(f"\r    {pct:3d}%  ({mb:.1f} MB)")
            sys.stdout.flush()

    # Use the default SSL context so HTTPS certificates are verified.
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context)
    )
    urllib.request.install_opener(opener)
    urllib.request.urlretrieve(url, dest_path, reporthook=report)
    sys.stdout.write("\n")


def _download_curl(url, dest_path):
    """Fall back to the system `curl`, which uses the OS certificate store.

    This avoids the common macOS error where python.org Python can't find the CA
    certificates (SSL: CERTIFICATE_VERIFY_FAILED).
    """
    subprocess.run(
        ["curl", "-fL", "--retry", "3", "-o", dest_path, url], check=True
    )


def download(url, dest_path):
    """Try urllib first; if the SSL/cert step fails, fall back to curl."""
    try:
        _download_urllib(url, dest_path)
    except (urllib.error.URLError, ssl.SSLError) as e:
        print(f"    (urllib failed: {e}; trying curl instead)")
        if shutil.which("curl") is None:
            raise
        _download_curl(url, dest_path)


def main():
    os.makedirs(DEST_DIR, exist_ok=True)
    print(f"Downloading BDG2 data into ./{DEST_DIR}/ ...")
    for filename, url in FILES.items():
        dest = os.path.join(DEST_DIR, filename)
        if os.path.exists(dest):
            print(f"  {filename}: already exists, skipping "
                  f"(delete it to re-download).")
            continue
        print(f"  {filename}:")
        try:
            download(url, dest)
        except Exception as e:  # noqa: BLE001 - keep it simple for a beginner
            print(f"    FAILED: {e}")
            print(f"    URL was: {url}")
            sys.exit(1)
    print("\nDone. You can now run: python data_pipeline.py")
    print("Data source: Building Data Genome Project 2 (Miller et al., 2020).")


if __name__ == "__main__":
    main()
