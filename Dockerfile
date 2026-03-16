FROM ubuntu:22.04
LABEL description="This is a docker image to run tests using P4-SpecTec, HOL4P4 and Petr4"
ARG DEBIAN_FRONTEND=noninteractive
ENV DEBCONF_NOWARNINGS="yes"
USER root

# ========= HOL4P4 =========
COPY ./hol4p4 /HOL4P4

# This lets us use the same installation scripts
RUN apt update && apt-get install -y -q sudo vim

# Then, just run the regular install script
RUN ./HOL4P4/scripts/install.sh
WORKDIR /HOL4P4/hol/p4_from_json

# Copy additional include headers used by test suite
COPY ./hol4p4/p4include/ /HOL4P4/hol/p4_from_json/p4include/

# ========= PETR4 =========
ENV PETR4_DEPS="pkg-config \
               sudo \
               git \
               m4 \
               vim \
               libgmp-dev \
               opam \
               ca-certificates \
               curl \
               unzip"

COPY ./petr4 /petr4/
WORKDIR /petr4/

RUN apt-get update && \
    apt-get install -y --no-install-recommends $PETR4_DEPS

RUN opam switch create . --empty && \
    eval $(opam env) && \
    opam switch import petr4-013.export -y && \
    eval $(opam env) && \
    dune build && \
    dune install

# ========= P4-SpecTec =========
COPY ./p4-spectec /p4-spectec
WORKDIR /p4-spectec

RUN opam switch create 5.1.0 && \
    eval $(opam env) && \
    opam update && \
    opam install dune bignum 'menhir=20240715' 'menhirLib=20240715' core core_unix bisect_ppx yojson ppx_deriving_yojson -y && \
    eval $(opam env) && \
    make release

WORKDIR /
COPY ./testdata /
COPY ./p4include /
COPY ./scripts /

ENTRYPOINT ["/bin/bash", "--login"]
