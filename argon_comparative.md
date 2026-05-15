# ARGON Precision - Estado Actual

Benchmark usado: `Astryd_Sophia` como proyecto de prueba real, no como objetivo específico de optimización.

## Resultado Actual

Comando usado:

```powershell
python argon.py C:\Users\maruc\Desktop\proyecto\Astryd_Sophia --precision --task "understand architecture and call graph" --budget 6000 --format json --view --output %TEMP%\argon_astryd_sophia_precision
```

Resultado observado:

| Métrica | Resultado |
|---|---:|
| Archivos escaneados | 317 |
| Conexiones entre archivos | 613 |
| Símbolos detectados | 3538 |
| Conexiones entre símbolos | 3876 |
| Llamadas símbolo-a-símbolo | 547 |
| Imports locales no resueltos | 0 |
| Budget solicitado | 6000 tokens |
| Budget usado | ~5986 tokens |

## Qué Cambió Frente A Argon v9 Clásico

Argon ya no es solo un scanner visual por archivo. En modo Precision ahora incluye:

- Conteo real de tokens con `tiktoken`.
- Ignorados reales con `.gitignore`, `.ignore` y `.git/info/exclude`.
- Resolución de imports relativos, extensiones omitidas, extensiones compuestas como `.test.ts`, `index.*`, `baseUrl` y `paths` de `tsconfig.json`.
- Separación entre imports locales no resueltos y paquetes externos.
- Extracción de símbolos con rangos de líneas y firmas.
- Grafo de archivos.
- Grafo de símbolos.
- Edges `imports-symbol`.
- Edges `calls-symbol`.
- PageRank de archivos.
- Ranking de símbolos.
- Selección de contexto por tarea con:
  - keywords normalizadas,
  - camelCase/kebab-case/path splitting,
  - seeds por match directo,
  - callers/callees,
  - tests relacionados,
  - penalización de tipos globales demasiado genéricos,
  - degradación por budget.
- HTML Precision-aware con modos `FILES`, `SYMBOLS` y `CALLS`.
- MCP y watch integrados con Precision.

## Veredicto Honesto

| Área | Estado |
|---|---|
| Visualización de arquitectura | Fuerte |
| Contexto con budget real | Fuerte |
| Resolución TS/JS | Buena |
| Selección por tarea | Buena, mejorable |
| Call graph | Útil, pero todavía local/import-based |
| Nivel Aider repo-map | Cerca en algunas tareas, no igual |

Puntuación honesta aproximada:

```txt
Argon clásico:           3/10 para contexto IA
Argon Precision actual:  8/10 aproximado
Aider repo-map maduro:   8.5-9/10
```

No es honesto decir que Argon ya iguala a Aider en repo-map. Sí es razonable decir que Argon ahora compite como herramienta híbrida:

```txt
scanner + visualización + watch + MCP + contexto Precision
```

## Límites Pendientes

- El call graph todavía detecta llamadas a imports resueltos, pero no hace referencia AST completa dentro del mismo archivo.
- No hay embeddings ni búsqueda semántica real.
- Python/Java/C# necesitan benchmarks dedicados antes de afirmar precisión alta.
- La calidad depende de que tree-sitter-language-pack pueda extraer estructura suficiente para cada lenguaje.
- El selector por tarea ya es auditable, pero necesita benchmarks con expected symbols para medir precisión/recall formalmente.

## Próximo Trabajo Recomendado

1. Crear fixtures universales de regresión:
   - TS aliases
   - barrels
   - default exports
   - `.test.ts`
   - imports dentro de template strings
   - paquetes externos
   - Python imports
2. Añadir benchmark formal con `precision@budget` y `recall@budget`.
3. Mejorar referencias internas AST para llamadas dentro del mismo archivo.
4. Ampliar benchmarks a Python y monorepos TS.
