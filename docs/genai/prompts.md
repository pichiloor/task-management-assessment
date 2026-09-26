# Prompts

## Initial request — verbatim user prompt

The original Spanish request is preserved verbatim as evidence. Repository
instructions and authored documentation are in English. The broader example
prompt in the approved plan was not executed in this session.

```text
Tarea: ejecutar SOLO el paso 1 (entorno, repositorio y herramientas de calidad) de una prueba técnica. No implementes lógica de la aplicación; eso viene en pasos posteriores.

Contexto: el plan completo y aprobado está en /home/pichiloor/plan-prueba-tecnica-bla.md. Lee al menos las secciones 3 (Preparación del entorno), 4 (Stack), 5 (Arquitectura), 12 (Evidencia GenAI) y 13 (Estructura del repositorio) antes de empezar, y respeta lo que dicen.

Decisiones ya tomadas por el usuario:
- Nombre del repo: task-management-assessment, PÚBLICO, en la cuenta de GitHub pichiloor (gh CLI ya autenticado). Directorio local: /home/pichiloor/task-management-assessment
- Identidad de git: usar el correo noreply de GitHub de la cuenta (obtén el ID con `gh api user --jq .id` y arma `<id>+pichiloor@users.noreply.github.com`). Configúralo SOLO a nivel del repo (git config local), no global. Nombre: el que devuelva `gh api user --jq .name` (o pichiloor si viene vacío).
- Herramientas ya instaladas: uv 0.12.19 y pre-commit en ~/.local/bin, Python 3.12, Node v24. Docker está en WSL; si tu shell no tiene acceso al socket usa `sg docker -c "..."`. No uses Docker Desktop.

Qué debe quedar hecho:
1. Repo creado en GitHub (público) y enlazado en el directorio local, rama main.
2. Esqueleto de carpetas según la sección 13 del plan (backend/, frontend/, docs/, etc.), con archivos mínimos (__init__.py, .gitkeep) donde haga falta para que la estructura exista. Sin código de negocio.
3. backend/pyproject.toml gestionado con uv (Python 3.12), dependencias del stack del plan y grupo dev (pytest, pytest-cov, ruff, mypy, import-linter, etc.). Genera uv.lock. Configuración de Ruff, mypy y los contratos de import-linter que describe la arquitectura del plan.
4. .pre-commit-config.yaml con Ruff (lint + format), mypy y chequeos básicos (trailing whitespace, end-of-file, detección de secretos/archivos grandes). Instala los hooks (`pre-commit install`) y verifica que `pre-commit run --all-files` pase.
5. .gitignore y .editorconfig adecuados (Python, Node, .env, coverage, etc.). Un .env.example si el plan lo contempla. Nada de secretos reales en el repo.
6. CLAUDE.md en la raíz con las convenciones del proyecto (arquitectura, comandos, reglas de calidad) según el plan.
7. docs/ai-log.md (bitácora GenAI: abrir con la primera entrada real de esta sesión, indicando qué herramienta generó qué) y docs/thought-process.md (encabezado y secciones iniciales, con las decisiones ya tomadas del plan). No inventes contenido que no haya ocurrido.
8. README.md mínimo (título, descripción de una línea, "en construcción"); el README completo va al final.
9. Primer commit con mensaje claro y push a origin main.

No corras pytest ni suites de prueba (todavía no hay código). No modifiques nada fuera de /home/pichiloor/task-management-assessment salvo lo que requiera crear el repo en GitHub.

Al terminar, repórtame: URL del repo, hash del commit, árbol de archivos creado, salida resumida de `pre-commit run --all-files`, y cualquier decisión que hayas tomado por tu cuenta o desviación del plan.
```
