import sys
sys.path.insert(0, r'C:\Users\maruc\Proyectos\tools')
from argon import ArgonEngine
from argon_semantic import SemanticIndex

engine = ArgonEngine(r'C:\Users\maruc\Proyectos\Astryd_Sophia', precision=True)
graph = engine.build_graph()

semantic = SemanticIndex()
semantic.build_from_graph(graph)

for query in ['SparseRealMatrix definition', 'export matrix format', 'print matrix']:
    print(f'\n[*] Buscando: {query}')
    results = semantic.query(query, top_k=2)
    for score, sym in results:
        print(f' - [{score:.2f}] {sym.get("id")}')
