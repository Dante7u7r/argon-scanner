# ARGON — Universal Architecture Scanner

ARGON escanea proyectos de software y genera un grafo de arquitectura con:
- **Símbolos** (clases, funciones, interfaces) vía Tree-sitter o regex
- **Conexiones** entre archivos (imports/dependencias)
- **Visualización interactiva** con D3.js (SVG voxels) o PixiJS/WebGL (GPU)
- **MCP Server** para integración con asistentes IA
- **Watch mode** para actualización automática en cambios

## Instalación

```bash
pip install tree-sitter-language-pack  # opcional, para parser AST (~2MB)
pip install mcp                         # opcional, para MCP server

python argon.py . --context             # escanear proyecto actual
```

## Uso rápido

```bash
# Escanear proyecto
python argon.py /ruta/proyecto --context

# Generar visualización interactiva
python argon_view.py --json argon_graph.json

# Servidor MCP (para Claude, Cursor, etc.)
python argon_mcp.py

# Watch mode (actualización automática)
python argon_watch.py /ruta/proyecto
```

## Herramientas

| Comando | Descripción |
|---------|-------------|
| `argon.py` | Escáner universal con parser dual (Tree-sitter + regex) |
| `argon_view.py` | Genera visualización HTML interactiva |
| `argon_mcp.py` | Servidor MCP con 6 herramientas para IA |
| `argon_watch.py` | Sentinel que actualiza el grafo en cambios |
| `argon_template.html` | Template del visualizador D3.js/PixiJS |

## Visualización

- **< 500 nodos**: SVG voxels (cubos 3D isométricos, tema cyberpunk)
- **≥ 500 nodos**: PixiJS/WebGL (renderizado GPU, 10K+ nodos suaves)
- 6 temas visuales: Architect, Cyber, Fallout, Vaporwave, Matrix, Industrial
- Búsqueda por nombre de archivo, símbolo o concepto

## MCP Tools

| Tool | Descripción |
|------|-------------|
| `argon_overview` | Resumen del proyecto estadísticas y hubs |
| `argon_query` | Buscar símbolos específicos |
| `argon_deps` | Dependencias de un archivo |
| `argon_search` | Búsqueda por concepto/funcionalidad |
| `argon_focused_context` | Contexto optimizado para tareas específicas |
| `argon_rescan` | Regenerar grafo tras cambios |

## Licencia

MIT
