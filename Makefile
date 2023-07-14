.PHONY: bootstrap venv deps clean init runscript mypy pylint flake8 bandit release docs

FILES_CHECK_MYPY = mongodb_toolbox setup.py
FILES_CHECK_ALL = $(FILES_CHECK_MYPY) tests

bootstrap: venv deps dirs

venv:
	virtualenv -p python3 .env

deps:
	.env/bin/pip install -r requirements.txt
	.env/bin/pip install -e .

clean:
	find -name '*.pyc' -delete
	find -name '*.swp' -delete
	find -name '__pycache__' -delete

dirs:
	if [ ! -e var ]; then mkdir -p var; fi

mypy:
	mypy --strict $(FILES_CHECK_MYPY)

pylint:
	pylint -j0 $(FILES_CHECK_ALL)

flake8:
	flake8 -j auto --max-cognitive-complexity=8 $(FILES_CHECK_ALL)

bandit:
	bandit -qc pyproject.toml -r $(FILES_CHECK_ALL)

check: mypy pylint flake8 bandit

release:
	git push; git push --tags; rm dist/*; python3 setup.py clean sdist; twine upload --verbose dist/*

docs:
	sphinx-build -b html docs docs/_build

test:
	pytest
