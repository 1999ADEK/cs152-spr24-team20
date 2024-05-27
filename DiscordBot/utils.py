import datetime
from graphviz import Digraph

def visualize_heap(heap, highlight_report=None, highlight_color="grey"):
    if not heap:
        return
    
    dot = Digraph()

    def add_edges(dot, heap, idx):
        left_idx = 2 * idx + 1
        right_idx = 2 * idx + 2

        if left_idx < len(heap):
            dot.edge(f"{heap[idx][0]:.2f}", f"{heap[left_idx][0]:.2f}")
            add_edges(dot, heap, left_idx)
        
        if right_idx < len(heap):
            dot.edge(f"{heap[idx][0]:.2f}", f"{heap[right_idx][0]:.2f}")
            add_edges(dot, heap, right_idx)

    for value in heap:
        score, time, report = value
        if report == highlight_report:
            dot.node(f"{score:.2f}", shape="circle", style="filled", color=highlight_color)
        else:
            dot.node(f"{score:.2f}", shape="circle")

    add_edges(dot, heap, 0)

    timestamp = timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"heap_{timestamp}"
    dot.render(filename, format="png", cleanup=True)
    
    return filename + ".png"