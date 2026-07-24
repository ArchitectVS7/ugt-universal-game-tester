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
        "stable-baselines3",
        "playwright",
        "pyyaml",
    ],
    extras_require={
        "dashboard": ["tensorboard"],
        "playtest":  ["anthropic>=0.25.0", "python-dotenv>=1.0.0"],
        # Real-server adapter (drives a live game server over HTTP + Socket.IO).
        "realclient": ["requests", "python-socketio[client]>=5", "websocket-client"],
    },
    entry_points={
        "console_scripts": [
            "ugt=ugt.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
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
        "Programming Language :: Python :: 3.14",
    ],
)
