# P4-SpecTec Evaluation Harness

**Harness for evaluating P4-SpecTec, Petr4 and HOL4P4.**

All projects can be ran inside the docker container provided in `Dockerfile`.

# Setup

Clone the repo:
```bash
git clone https://github.com/pacokwon/p4-evaluation-harness

git submodule init
git submodule update
```

Build dockerfile:
```bash
docker build -t p4-eval-harness .
```

Run docker container:
```bash
docker run -dit --name p4-eval-harness p4-eval-harness
docker exec -it p4-eval-harness bash
```

Each project can be found in the root directory.
```
/
├── HOL4P4
├── petr4
└── p4-spectec
```
