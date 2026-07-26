from setuptools import setup, find_packages

setup(
    name="ugt-tester",
    version="1.0.0",
    description="Universal Game Tester (UGT) — agent-driven game testing: correctness, robustness, and LLM balance analysis",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Antigravity Team",
    python_requires=">=3.8",
    packages=find_packages(),
    install_requires=[
        "numpy",
        "gymnasium",
        "pyyaml",
    ],
    extras_require={
        # Playwright headless browser engine (engine.type: browser). Requires a
        # post-install step to fetch browser binaries: `playwright install chromium`.
        "browser":    ["playwright"],
        "playtest":   ["anthropic>=0.25.0", "python-dotenv>=1.0.0"],
    },
    entry_points={
        "console_scripts": [
            "ugt=ugt.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Games/Entertainment",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
)
