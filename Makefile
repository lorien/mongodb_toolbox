.PHONY: bootstrap venv deps clean init runscript mypy pytype pylint flake8 bandit release

FILES_FOR_CHECK = mongodb_toolbox setup.py

bootstrap: venv deps dirs

venv:
	virtualenv -p python3 .env

deps:
	.env/bin/pip install -r requirements.txt

clean:
	find -name '*.pyc' -delete
	find -name '*.swp' -delete
	find -name '__pycache__' -delete

dirs:
	if [ ! -e var ]; then mkdir -p var; fi

mypy:
	mypy --strict $(FILES_FOR_CHECK)

pytype:
	pytype -j auto $(FILES_FOR_CHECK)

pylint:
	pylint -j0 $(FILES_FOR_CHECK)

flake8:
	flake8 -j auto --max-cognitive-complexity=8 $(FILES_FOR_CHECK)

bandit:
	bandit -qc pyproject.toml -r $(FILES_FOR_CHECK)

check: mypy pylint flake8 pytype bandit

release:
	git push --tags; rm dist/*; python3 setup.py clean sdist; twine upload --verbose dist/*
