import os

from setuptools import find_packages, setup

ROOT = os.path.dirname(os.path.realpath(__file__))

with open("README.md", encoding="utf-8") as inp:
    readme_content = inp.read()

setup(
    name="ioweb",
    version="0.0.1",
    author="Gregory Petukhov",
    author_email="lorien@lorien.name",
    maintainer="Gregory Petukhov",
    maintainer_email="lorien@lorien.name",
    url="https://github.com/lorien/mongodb_tools",
    description="Tools to simplify common mongodb read/write usage patterns",
    long_description=readme_content,
    long_description_content_type="text/markdown",
    packages=find_packages(exclude=["test", "crawlers"]),
    download_url="https://github.com/lorien/mongodb_tools/releases",
    license="MIT",
    install_requires=[
        "pymongo",
    ],
    keywords="mongodb database",
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: Implementation :: CPython",
        "License :: OSI Approved :: MIT License",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
