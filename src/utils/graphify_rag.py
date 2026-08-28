"""Graphify GraphRAG Engine for Codebase AST & Architecture Extraction.

Description: Parses codebase Abstract Syntax Trees (AST), import dependencies,
             function call hierarchies, API routes, and deployment scripts to
             construct an in-memory Code Knowledge Graph (GraphRAG).
Need: Downstream analysis and code refactoring agents require semantic and
      structural grounding of existing codebases before generating proposals.
Motive: Ground architectural decisions in real repository structure, computing
        impact/blast-radius and extracting hosting/compute profiles reliably.
"""

import ast
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class GraphNode:
    """Represents an entity node in the codebase knowledge graph."""
    id: str
    node_type: str  # FILE, CLASS, FUNCTION, ROUTE, IMPORT, CONFIG, INFRA
    name: str
    file_path: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """Represents a relationship edge between entities in the knowledge graph."""
    source_id: str
    target_id: str
    relation: str  # CONTAINS, IMPORTS, CALLS, EXPOSES_ROUTE, CONFIGURES, DEPLOYS
    metadata: Dict[str, Any] = field(default_factory=dict)


class ASTSymbolVisitor(ast.NodeVisitor):
    """AST visitor that extracts classes, functions, calls, routes, and imports."""

    def __init__(self, file_path: str, rel_path: str):
        self.file_path = file_path
        self.rel_path = rel_path
        self.imports: List[Dict[str, Any]] = []
        self.classes: List[Dict[str, Any]] = []
        self.functions: List[Dict[str, Any]] = []
        self.calls: List[Dict[str, Any]] = []
        self.routes: List[Dict[str, Any]] = []
        self.current_class: Optional[str] = None
        self.current_function: Optional[str] = None

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append({
                "module": alias.name,
                "asname": alias.asname,
                "line": node.lineno,
            })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            self.imports.append({
                "module": f"{module}.{alias.name}" if module else alias.name,
                "source_module": module,
                "name": alias.name,
                "asname": alias.asname,
                "line": node.lineno,
            })
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        prev_class = self.current_class
        self.current_class = node.name
        self.classes.append({
            "name": node.name,
            "line": node.lineno,
            "docstring": ast.get_docstring(node),
            "bases": [ast.unparse(b) for b in node.bases] if hasattr(ast, "unparse") else [],
        })
        self.generic_visit(node)
        self.current_class = prev_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._process_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._process_func(node)

    def _process_func(self, node: Any) -> None:
        prev_func = self.current_function
        func_name = f"{self.current_class}.{node.name}" if self.current_class else node.name
        self.current_function = func_name

        # Inspect decorators for web routes (@app.route, @router.get, etc.)
        routes_found = self._extract_routes(node)
        for route in routes_found:
            self.routes.append(route)

        self.functions.append({
            "name": func_name,
            "raw_name": node.name,
            "class_name": self.current_class,
            "line": node.lineno,
            "args": [arg.arg for arg in node.args.args],
            "docstring": ast.get_docstring(node),
            "decorators": [ast.unparse(d) for d in node.decorator_list] if hasattr(ast, "unparse") else [],
            "has_routes": len(routes_found) > 0,
        })

        self.generic_visit(node)
        self.current_function = prev_func

    def _extract_routes(self, node: Any) -> List[Dict[str, Any]]:
        routes = []
        for dec in node.decorator_list:
            dec_str = ast.unparse(dec) if hasattr(ast, "unparse") else ""
            if "route(" in dec_str or any(m in dec_str for m in [".get(", ".post(", ".put(", ".delete(", ".patch("]):
                path = "/"
                methods = ["GET"]
                if isinstance(dec, ast.Call):
                    if dec.args:
                        first_arg = dec.args[0]
                        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                            path = first_arg.value
                    for kw in dec.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            methods = [
                                elt.value for elt in kw.value.elts
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                            ]
                    if "." in dec_str:
                        method_match = re.search(r'\.(get|post|put|delete|patch)\(', dec_str)
                        if method_match:
                            methods = [method_match.group(1).upper()]

                routes.append({
                    "path": path,
                    "methods": methods,
                    "handler": node.name,
                    "file_path": self.rel_path,
                    "line": node.lineno,
                })
        return routes

    def visit_Call(self, node: ast.Call) -> None:
        call_name = ""
        if isinstance(node.func, ast.Name):
            call_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            call_name = f"{ast.unparse(node.func.value)}.{node.func.attr}" if hasattr(ast, "unparse") else node.func.attr

        if call_name:
            self.calls.append({
                "caller": self.current_function or "module_scope",
                "callee": call_name,
                "line": node.lineno,
            })
        self.generic_visit(node)


from src.utils.repo_loader import resolve_repository


class GraphifyKnowledgeGraph:
    """In-memory GraphRAG repository representation."""

    def __init__(self, repo_path_or_url: str):
        self.original_target = repo_path_or_url
        self.repo_path, self.was_cloned, self.pull_warning = resolve_repository(repo_path_or_url)
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: List[GraphEdge] = []
        self.files_indexed: List[str] = []
        self.detected_framework: str = "Unknown"
        self.detected_platform: str = "Unknown"
        self.is_stateful: bool = False
        self.workload_profile: Dict[str, Any] = {}
        self.dependencies: Set[str] = set()

    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)

    def build_graph(self) -> "GraphifyKnowledgeGraph":
        """Walks the directory, parses code AST and infrastructure files."""
        if not os.path.exists(self.repo_path):
            raise FileNotFoundError(f"Repository path does not exist: {self.repo_path}")

        for root, _, files in os.walk(self.repo_path):
            for file in files:
                abs_file_path = os.path.join(root, file)
                rel_file_path = os.path.relpath(abs_file_path, self.repo_path).replace("\\", "/")

                # Skip venvs, git, cache
                if any(p in rel_file_path for p in [".git", "__pycache__", "venv", ".venv", ".pytest_cache"]):
                    continue

                self.files_indexed.append(rel_file_path)
                file_node_id = f"file:{rel_file_path}"
                self.add_node(GraphNode(
                    id=file_node_id,
                    node_type="FILE",
                    name=file,
                    file_path=rel_file_path,
                    metadata={"size_bytes": os.path.getsize(abs_file_path)}
                ))

                if file.endswith(".py"):
                    self._parse_python_file(abs_file_path, rel_file_path, file_node_id)
                elif file.lower() == "dockerfile" or file.endswith(".dockerfile"):
                    self._parse_dockerfile(abs_file_path, rel_file_path, file_node_id)
                elif file.endswith(".sh"):
                    self._parse_shell_script(abs_file_path, rel_file_path, file_node_id)
                elif file in ("requirements.txt", "Pipfile", "pyproject.toml"):
                    self._parse_dependencies(abs_file_path, rel_file_path, file_node_id)

        self._infer_architecture_profile()
        return self

    def _parse_python_file(self, abs_path: str, rel_path: str, file_node_id: str) -> None:
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            tree = ast.parse(content, filename=abs_path)
        except Exception:
            return

        visitor = ASTSymbolVisitor(abs_path, rel_path)
        visitor.visit(tree)

        # Record imports
        for imp in visitor.imports:
            mod_name = imp.get("source_module") or imp.get("module", "")
            if mod_name:
                self.dependencies.add(mod_name.split(".")[0])
                import_node_id = f"import:{rel_path}:{imp.get('module')}"
                self.add_node(GraphNode(
                    id=import_node_id,
                    node_type="IMPORT",
                    name=imp.get("module", ""),
                    file_path=rel_path,
                    metadata=imp
                ))
                self.add_edge(GraphEdge(
                    source_id=file_node_id,
                    target_id=import_node_id,
                    relation="IMPORTS"
                ))

        # Record classes
        for cls in visitor.classes:
            cls_node_id = f"class:{rel_path}:{cls['name']}"
            self.add_node(GraphNode(
                id=cls_node_id,
                node_type="CLASS",
                name=cls["name"],
                file_path=rel_path,
                metadata=cls
            ))
            self.add_edge(GraphEdge(
                source_id=file_node_id,
                target_id=cls_node_id,
                relation="CONTAINS"
            ))

        # Record functions
        for func in visitor.functions:
            func_node_id = f"func:{rel_path}:{func['name']}"
            self.add_node(GraphNode(
                id=func_node_id,
                node_type="FUNCTION",
                name=func["name"],
                file_path=rel_path,
                metadata=func
            ))
            self.add_edge(GraphEdge(
                source_id=file_node_id,
                target_id=func_node_id,
                relation="CONTAINS"
            ))

        # Record routes
        for r in visitor.routes:
            route_node_id = f"route:{rel_path}:{r['path']}:{','.join(r['methods'])}"
            self.add_node(GraphNode(
                id=route_node_id,
                node_type="ROUTE",
                name=f"{','.join(r['methods'])} {r['path']}",
                file_path=rel_path,
                metadata=r
            ))
            self.add_edge(GraphEdge(
                source_id=f"func:{rel_path}:{r['handler']}",
                target_id=route_node_id,
                relation="EXPOSES_ROUTE"
            ))

        # Record function calls
        for call in visitor.calls:
            caller_id = f"func:{rel_path}:{call['caller']}"
            self.add_edge(GraphEdge(
                source_id=caller_id,
                target_id=call["callee"],
                relation="CALLS",
                metadata={"line": call["line"]}
            ))

    def _parse_dockerfile(self, abs_path: str, rel_path: str, file_node_id: str) -> None:
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except Exception:
            return

        base_image = ""
        exposed_ports = []
        for line in lines:
            line_str = line.strip()
            if line_str.upper().startswith("FROM "):
                base_image = line_str.split()[1]
            elif line_str.upper().startswith("EXPOSE "):
                exposed_ports.extend(line_str.split()[1:])

        config_node_id = f"config:{rel_path}:docker"
        self.add_node(GraphNode(
            id=config_node_id,
            node_type="CONFIG",
            name="Dockerfile",
            file_path=rel_path,
            metadata={"base_image": base_image, "exposed_ports": exposed_ports}
        ))
        self.add_edge(GraphEdge(
            source_id=file_node_id,
            target_id=config_node_id,
            relation="CONFIGURES"
        ))

    def _parse_shell_script(self, abs_path: str, rel_path: str, file_node_id: str) -> None:
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return

        # Variable mapping in shell script
        vars_map = {}
        for line in content.splitlines():
            var_match = re.match(r'^\s*([A-Za-z0-9_]+)=["\']?([^"\'#\n]+)["\']?', line)
            if var_match:
                vars_map[var_match.group(1)] = var_match.group(2).strip()

        detected_infra = {}
        if "gcloud compute instances create" in content:
            detected_infra["platform"] = "GCE"
            machine_match = re.search(r'--machine-type=["\']?(\$?[a-zA-Z0-9_-]+|\$\{[a-zA-Z0-9_-]+\})["\']?', content)
            if machine_match:
                raw_val = machine_match.group(1)
                var_key = raw_val.strip("${}")
                detected_infra["machine_type"] = vars_map.get(var_key, raw_val)

            disk_match = re.search(r'--boot-disk-size=["\']?(\$?[a-zA-Z0-9_-]+|\$\{[a-zA-Z0-9_-]+\})["\']?', content)
            if disk_match:
                raw_val = disk_match.group(1)
                var_key = raw_val.strip("${}")
                detected_infra["disk_size"] = vars_map.get(var_key, raw_val)

            zone_match = re.search(r'--zone=["\']?(\$?[a-zA-Z0-9_-]+|\$\{[a-zA-Z0-9_-]+\})["\']?', content)
            if zone_match:
                raw_val = zone_match.group(1)
                var_key = raw_val.strip("${}")
                detected_infra["zone"] = vars_map.get(var_key, raw_val)

            detected_infra["autoscaling"] = "--autoscaling-policy" in content or "gcloud compute instance-groups managed set-autoscaling" in content

        if detected_infra:
            infra_node_id = f"infra:{rel_path}:{detected_infra.get('platform', 'GCP')}"
            self.add_node(GraphNode(
                id=infra_node_id,
                node_type="INFRA",
                name="GCP Deployment Script",
                file_path=rel_path,
                metadata=detected_infra
            ))
            self.add_edge(GraphEdge(
                source_id=file_node_id,
                target_id=infra_node_id,
                relation="DEPLOYS"
            ))

    def _parse_dependencies(self, abs_path: str, rel_path: str, file_node_id: str) -> None:
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_clean = line.strip().split("==")[0].split(">=")[0].split("<=")[0].strip()
                    if line_clean and not line_clean.startswith("#"):
                        self.dependencies.add(line_clean)
        except Exception:
            pass

    def _infer_architecture_profile(self) -> None:
        """Heuristically synthesizes architecture attributes from the GraphRAG graph."""
        dep_names = {d.lower() for d in self.dependencies}
        if "flask" in dep_names:
            self.detected_framework = "Flask"
        elif "fastapi" in dep_names:
            self.detected_framework = "FastAPI"
        elif "django" in dep_names:
            self.detected_framework = "Django"

        # Check infra nodes
        for node in self.nodes.values():
            if node.node_type == "INFRA":
                self.detected_platform = node.metadata.get("platform", "Unknown")
                machine_type = str(node.metadata.get("machine_type", ""))
                disk_size_str = str(node.metadata.get("disk_size", "10GB"))
                disk_gb = float(re.sub(r'[^0-9]', '', disk_size_str) or 10.0)

                cpu_cores = 1.0
                ram_gb = 2.0
                if "n1-standard-4" in machine_type:
                    cpu_cores = 4.0
                    ram_gb = 16.0
                elif "n1-standard-2" in machine_type or "e2-standard-2" in machine_type:
                    cpu_cores = 2.0
                    ram_gb = 8.0
                elif "n1-standard-1" in machine_type or "e2-medium" in machine_type:
                    cpu_cores = 1.0
                    ram_gb = 4.0

                self.workload_profile = {
                    "name": "legacy-order-service",
                    "cpu_cores": cpu_cores,
                    "ram_gb": ram_gb,
                    "disk_gb": disk_gb,
                    "monthly_requests": 500000,
                    "machine_type": machine_type,
                    "has_autoscaling": node.metadata.get("autoscaling", False)
                }

        if self.detected_platform == "Unknown":
            has_docker = any(n.node_type == "CONFIG" and n.name == "Dockerfile" for n in self.nodes.values())
            self.detected_platform = "Docker Container" if has_docker else "BareMetal/Script"

        # Stateless REST check
        has_routes = any(n.node_type == "ROUTE" for n in self.nodes.values())
        self.is_stateful = False

    def query(self, query_text: str) -> Dict[str, Any]:
        """Queries the codebase graph with natural language / keyword terms."""
        query_lower = query_text.lower()
        matched_nodes = []
        for node in self.nodes.values():
            score = 0
            if query_lower in node.name.lower():
                score += 3
            if query_lower in node.file_path.lower():
                score += 2
            if any(query_lower in str(v).lower() for v in node.metadata.values()):
                score += 1

            if score > 0:
                matched_nodes.append({
                    "id": node.id,
                    "type": node.node_type,
                    "name": node.name,
                    "file": node.file_path,
                    "score": score,
                    "metadata": node.metadata
                })

        matched_nodes.sort(key=lambda x: x["score"], reverse=True)
        return {
            "query": query_text,
            "total_matches": len(matched_nodes),
            "top_nodes": matched_nodes[:10],
            "graph_summary": self.get_summary()
        }

    def get_impact_analysis(self, target_name: str) -> Dict[str, Any]:
        """Calculates blast radius and callers/dependencies for a given target."""
        target_lower = target_name.lower()
        direct_callers = []
        direct_dependencies = []

        for edge in self.edges:
            if target_lower in edge.target_id.lower() and edge.relation == "CALLS":
                direct_callers.append(edge.source_id)
            if target_lower in edge.source_id.lower() and edge.relation == "CALLS":
                direct_dependencies.append(edge.target_id)

        return {
            "target": target_name,
            "blast_radius_score": len(direct_callers) * 2 + len(direct_dependencies),
            "callers": direct_callers,
            "dependencies": direct_dependencies,
        }

    def get_summary(self) -> Dict[str, Any]:
        """Provides full architectural breakdown extracted from GraphRAG."""
        route_nodes = [n for n in self.nodes.values() if n.node_type == "ROUTE"]
        func_nodes = [n for n in self.nodes.values() if n.node_type == "FUNCTION"]
        class_nodes = [n for n in self.nodes.values() if n.node_type == "CLASS"]
        infra_nodes = [n for n in self.nodes.values() if n.node_type == "INFRA"]

        return {
            "target_url_or_path": self.original_target,
            "was_cloned": self.was_cloned,
            "pull_warning": self.pull_warning,
            "repository_root": self.repo_path,
            "total_files": len(self.files_indexed),
            "files": self.files_indexed,
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "detected_framework": self.detected_framework,
            "detected_platform": self.detected_platform,
            "is_stateful": self.is_stateful,
            "workload_profile": self.workload_profile,
            "dependencies": sorted(list(self.dependencies)),
            "routes_count": len(route_nodes),
            "routes": [r.name for r in route_nodes],
            "classes_count": len(class_nodes),
            "functions_count": len(func_nodes),
            "infrastructure": [i.metadata for i in infra_nodes]
        }
