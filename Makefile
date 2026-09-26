.PHONY: validate build clean-build test eval smoke schemas lint

UV ?= uv
RUN = $(UV) run

validate:
	$(RUN) animedex validate

build:
	$(RUN) animedex build

clean-build:
	rm -rf build
	$(RUN) animedex build --verify-determinism

test:
	$(RUN) pytest -q

eval:
	$(RUN) animedex eval

smoke:
	$(RUN) animedex smoke $(if $(TITLE),--title $(TITLE),)

schemas:
	$(RUN) animedex schemas

lint:
	$(RUN) ruff check .
