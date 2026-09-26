from aiassetstudio.comfy.graphs import (
    ACE_OUTPUT_NODE,
    KEYSCALES,
    QWEN_ENCODE_OUTPUT_NODE,
    QWEN_OUTPUT_NODE,
    QWEN_TE,
    QWEN_UNET,
    QWEN_VAE,
    VIGGLE_LORA,
    YUE2_OUTPUT_NODE,
    Reference,
    ace_music,
    qwen_ref_turbo,
    qwen_t2i_turbo,
    qwen_text_encode,
    yue2_song,
)


def links(graph: dict):
    for node_id, node in graph.items():
        for name, value in node["inputs"].items():
            if isinstance(value, list):
                yield node_id, name, value


def test_all_links_point_to_existing_nodes():
    for graph in (qwen_t2i_turbo("p", seed=1, prefix="x"), qwen_text_encode("p")):
        found = list(links(graph))
        assert found
        for node_id, name, (target, index) in found:
            assert target in graph, f"{node_id}.{name} -> missing node {target}"
            assert isinstance(index, int) and index >= 0


def test_ref_graphs_links_and_modes():
    for mode in ("latent", "vision"):
        graph = qwen_ref_turbo("p", seed=1, prefix="x", ref_name="aiassetstudio/ref.png", mode=mode)
        for node_id, name, (target, _) in links(graph):
            assert target in graph, f"{node_id}.{name} -> missing node {target}"
        encode = graph["5"]["inputs"]
        assert graph["15"] == {"class_type": "LoadImage", "inputs": {"image": "aiassetstudio/ref.png"}}
        assert graph["16"]["class_type"] == "JoinImageWithAlpha"
        assert graph["16"]["inputs"] == {"image": ["15", 0], "alpha": ["15", 1]}  # the mask is 1 - alpha
        assert encode["images.image_1"] == ["16", 0]
        assert ("vae" in encode) == (mode == "latent")
        assert graph["6"]["class_type"] == "EmptyLatentImage"  # output size does not follow the reference
        assert graph["10"]["inputs"]["model"] == ["2", 0]


def test_ref_encode_graph_matches_full_graph():
    ref = Reference("aiassetstudio/ref.png", "latent")
    encode = qwen_text_encode("a slime", ref)
    full = qwen_t2i_turbo("a slime", seed=3, prefix="x", ref=ref)
    shared = {"3", "4", "5", "15", "16"}
    assert shared <= set(encode)
    assert {k: encode[k] for k in shared} == {k: full[k] for k in shared}
    for node_id, name, (target, _) in links(encode):
        assert target in encode, f"{node_id}.{name} -> missing node {target}"


def test_cache_cpu_sits_between_lora_and_guider():
    graph = qwen_ref_turbo("p", seed=1, prefix="x", ref_name="r.png", mode="latent", cache_cpu=True)
    assert graph["17"] == {
        "class_type": "QwenImage21Cache",
        "inputs": {"model": ["2", 0], "device": "cpu", "dtype": "default"},
    }
    assert graph["10"]["inputs"]["model"] == ["17", 0]


def test_encode_graph_matches_full_graph_text_nodes():
    # ComfyUI reuses cached outputs only for identical nodes, so the candidates must see the same "3" and "5".
    encode = qwen_text_encode("a slime")
    full = qwen_t2i_turbo("a slime", seed=5, prefix="x")
    assert {k: encode[k] for k in ("3", "5")} == {k: full[k] for k in ("3", "5")}
    assert encode[QWEN_ENCODE_OUTPUT_NODE] == {"class_type": "PreviewAny", "inputs": {"source": ["5", 0]}}
    assert set(encode) == {"3", "5", QWEN_ENCODE_OUTPUT_NODE}


def test_values_are_filled_in():
    graph = qwen_t2i_turbo("a green slime", seed=1234, prefix="smoke_abc", width=768, height=512)
    assert graph["5"]["inputs"]["prompt"] == "a green slime"
    assert graph["11"]["inputs"]["noise_seed"] == 1234
    assert graph["6"]["inputs"]["width"] == 768
    assert graph["6"]["inputs"]["height"] == 512
    out = graph[QWEN_OUTPUT_NODE]
    assert out["class_type"] == "SaveImage"
    assert out["inputs"]["filename_prefix"] == "aiassetstudio/smoke_abc"


def test_model_files():
    graph = qwen_t2i_turbo("p", seed=1, prefix="x")
    assert graph["1"]["inputs"]["unet_name"] == QWEN_UNET
    assert graph["3"]["inputs"]["clip_name"] == QWEN_TE
    assert graph["3"]["inputs"]["type"] == "qwen_image"
    assert graph["4"]["inputs"]["vae_name"] == QWEN_VAE
    assert graph["2"]["inputs"]["lora_name"] == VIGGLE_LORA


def check_links(graph: dict) -> None:
    found = list(links(graph))
    assert found
    for node_id, name, (target, index) in found:
        assert target in graph, f"{node_id}.{name} -> missing node {target}"
        assert isinstance(index, int) and index >= 0


def test_ace_music():
    graph = ace_music(
        "cozy village, flute", "[Main Theme]", bpm=96, seconds=90.0, keyscale="G major", seed=7, prefix="p"
    )
    check_links(graph)
    encode = graph["94"]["inputs"]
    assert (encode["tags"], encode["lyrics"], encode["bpm"], encode["keyscale"]) == (
        "cozy village, flute",
        "[Main Theme]",
        96,
        "G major",
    )
    assert encode["duration"] == graph["98"]["inputs"]["seconds"] == 90.0  # the song and the latent agree
    assert (encode["language"], encode["timesignature"], encode["seed"]) == ("unknown", "4", 7)
    sampler = graph["3"]["inputs"]
    assert (sampler["steps"], sampler["cfg"], sampler["sampler_name"], sampler["seed"]) == (8, 1.0, "euler", 7)
    assert graph[ACE_OUTPUT_NODE] == {
        "class_type": "SaveAudio",
        "inputs": {"audio": ["18", 0], "filename_prefix": "aiassetstudio/p"},
    }
    assert "A minor" in KEYSCALES and len(KEYSCALES) == 34


def test_yue2_song():
    lyrics = "[Verse]\n창가에 스친 빗소리"
    graph = yue2_song("K-pop ballad, 76 BPM", lyrics, seed=3, max_duration=60.0, prefix="v")
    check_links(graph)
    assert graph["25"]["inputs"]["abc"] == ["24", 0]  # ABC mode: the score first
    assert graph["25"]["inputs"]["max_duration"] == 60.0
    assert graph["5"]["inputs"]["seconds"] == ["25", 1]  # the length comes from the generated song
    assert graph["24"]["inputs"]["lyrics"] == graph["25"]["inputs"]["lyrics"] == lyrics
    sampler = graph["8"]["inputs"]
    assert (sampler["steps"], sampler["sampler_name"], sampler["scheduler"]) == (32, "dpm_2", "sgm_uniform")
    assert graph[YUE2_OUTPUT_NODE]["inputs"]["filename_prefix"] == "aiassetstudio/v"
    assert "PreviewAny" not in {node["class_type"] for node in graph.values()}
