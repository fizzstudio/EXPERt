# syntax=docker/dockerfile:1

FROM python:3.10.5
WORKDIR /app
COPY pyproject.toml pyproject.toml
RUN pip3 install pdm
RUN mkdir __pypackages__
RUN pdm install
COPY docker_start.sh docker_start.sh
COPY cfg.json cfg.json
COPY expert_cfg.json expert_cfg.json
COPY expert expert
COPY runexp.py runexp.py
EXPOSE 5000
#ENTRYPOINT [ "bash", "-c", "eval \"$(pdm --pep582)\"; exec python3 runexp.py $@" ]
ENTRYPOINT [ "/bin/bash", "docker_start.sh" ]
