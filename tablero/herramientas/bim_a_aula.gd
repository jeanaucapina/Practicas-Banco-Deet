## Hornea BIM-DT_Laboratorio0.2 a GLB (evaluacion, ver docs/EVALUACION_BIM_DT.md). Rutas fijas de /tmp/claude-0/bim/:
## copiar Modelos/Laboratorio_mallas a /tmp/claude-0/bim/proj/ y correr: godot --headless --xr-mode off --path /tmp/claude-0/bim/proj --script hornear.gd
extends SceneTree
const TSCN := "/home/user/Quest3_Projects/BIM-DT_Laboratorio0.2/Escenas/Laboratorio/Laboratorio0.2.tscn"
func _init():
	var txt := FileAccess.get_file_as_string(TSCN)
	var re := RegEx.new(); re.compile('ext_resource type="ArrayMesh" path="res://Modelos/Laboratorio_mallas/([^"]+)" id="(malla_\\d+)"')
	var id2f := {}
	for m in re.search_all(txt): id2f[m.get_string(2)] = m.get_string(1)
	var raiz := Node3D.new(); raiz.name = "AulaBIM"
	var giro := Basis(Vector3.UP, PI)   # (x,y,z)->(-x,y,-z)
	var tris := 0; var mats := {}; var surfs := 0; var tris_sin_lamp := 0
	var granito := StandardMaterial3D.new(); granito.albedo_color = Color(0.62,0.63,0.60); granito.roughness = 0.7
	var pared := StandardMaterial3D.new(); pared.albedo_color = Color(0.99,0.99,0.98); pared.roughness = 0.85
	for b in txt.split("\n[node "):
		var mm := RegEx.create_from_string('mesh = ExtResource\\("(malla_\\d+)"\\)').search(b)
		if mm == null: continue
		var f: String = id2f[mm.get_string(1)]
		var nombre := b.get_slice('"', 1)
		var mesh := load("/tmp/claude-0/bim/proj/Modelos/Laboratorio_mallas/" + f) as ArrayMesh
		var mi := MeshInstance3D.new(); mi.name = nombre
		if f.begins_with("IfcLamp"):
			var bx := BoxMesh.new(); bx.size = mesh.get_aabb().size
			mi.mesh = bx; mi.position = mesh.get_aabb().get_center()
			var em := StandardMaterial3D.new(); em.albedo_color = Color.WHITE; em.emission_enabled = true; em.emission = Color.WHITE
			bx.material = em
			tris += 12
		else:
			mi.mesh = mesh
			var t := 0
			for s in mesh.get_surface_count():
				var a := mesh.surface_get_arrays(s); var idx = a[Mesh.ARRAY_INDEX]
				t += (idx.size() if idx != null else a[Mesh.ARRAY_VERTEX].size())/3
				var mt := mesh.surface_get_material(s)
				mats[mt.resource_path if mt.resource_path != "" else str(mt.get_instance_id())] = 1
			tris += t; surfs += mesh.get_surface_count()
			if "material_override" in b:
				mi.material_override = pared if b.contains('5_h8txj') else granito
		mi.transform = Transform3D(giro, Vector3.ZERO) * mi.transform
		raiz.add_child(mi)
		mi.owner = raiz
	print("nodos=", raiz.get_child_count(), " tris=", tris, " superficies=", surfs, " materiales distintos(por recurso)=", mats.size())
	var doc := GLTFDocument.new(); var st := GLTFState.new()
	var e := doc.append_from_scene(raiz, st)
	e = doc.write_to_filesystem(st, "/tmp/claude-0/bim/aula_bim.glb")
	print("export err=", e)
	quit()
