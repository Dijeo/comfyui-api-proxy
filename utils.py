import json
import copy

def load_workflow_template(template_path: str) -> dict:
    with open(template_path, "r") as f:
        return json.load(f)

def update_workflow_inputs(workflow: dict, inputs: dict) -> dict:
    """
    Updates the workflow dictionary with provided inputs.
    
    Args:
        workflow: The loaded workflow dictionary (API format).
        inputs: A dictionary of inputs to update. 
                Keys should map to node IDs or specific logical names if we map them.
                For this simple version, we'll assume inputs keys map to:
                - "prompt": Updates positive prompt text (Node 6)
                - "seed": Updates KSampler seed (Node 3)
    """
    new_workflow = copy.deepcopy(workflow)
    
    # Simple mapping logic for the template
    # Helper to find node by class type
    def find_node_by_class(workflow, class_type):
        for node_id, node in workflow.items():
            if node.get("class_type") == class_type:
                return node_id, node
        return None, None

    # Update Prompt (CLIPTextEncode)
    # We assume the one with "positive" or just the first one is positive if we can't distinguish,
    # but usually we rely on IDs. Let's try to stick to the IDs we defined in templates.
    
    # Text2Img / Img2Img (Juggernaut) IDs: 6 (Pos), 7 (Neg), 3 (KSampler), 5/10 (Latent), 11 (LoadImage)
    # Text2Vid (Wan) IDs: 2 (Pos), 3 (Neg), 5 (KSampler), 4 (Latent)
    # Img2Vid (Wan) IDs: 2 (Pos), 3 (Neg), 6 (KSampler), 5 (Latent), 4 (LoadImage)

    # Positive Prompt
    if "prompt" in inputs:
        if "6" in new_workflow: new_workflow["6"]["inputs"]["text"] = inputs["prompt"]
        elif "2" in new_workflow: new_workflow["2"]["inputs"]["text"] = inputs["prompt"]

    # Negative Prompt
    if "negative_prompt" in inputs:
        if "7" in new_workflow: new_workflow["7"]["inputs"]["text"] = inputs["negative_prompt"]
        elif "3" in new_workflow: new_workflow["3"]["inputs"]["text"] = inputs["negative_prompt"]

    # KSampler
    sampler_id = None
    if "3" in new_workflow and new_workflow["3"]["class_type"] == "KSampler": sampler_id = "3"
    elif "5" in new_workflow and new_workflow["5"]["class_type"] == "KSampler": sampler_id = "5"
    elif "6" in new_workflow and new_workflow["6"]["class_type"] == "KSampler": sampler_id = "6"

    if sampler_id:
        if "seed" in inputs: new_workflow[sampler_id]["inputs"]["seed"] = inputs["seed"]
        if "steps" in inputs: new_workflow[sampler_id]["inputs"]["steps"] = inputs["steps"]
        if "cfg" in inputs: new_workflow[sampler_id]["inputs"]["cfg"] = inputs["cfg"]
        if "sampler_name" in inputs: new_workflow[sampler_id]["inputs"]["sampler_name"] = inputs["sampler_name"]
        if "scheduler" in inputs: new_workflow[sampler_id]["inputs"]["scheduler"] = inputs["scheduler"]

    # Empty Latent (Dimensions)
    latent_id = None
    if "5" in new_workflow and new_workflow["5"]["class_type"] == "EmptyLatentImage": latent_id = "5"
    elif "4" in new_workflow and new_workflow["4"]["class_type"] == "EmptyLatentImage": latent_id = "4"
    
    if latent_id:
        if "width" in inputs: new_workflow[latent_id]["inputs"]["width"] = inputs["width"]
        if "height" in inputs: new_workflow[latent_id]["inputs"]["height"] = inputs["height"]
        if "batch_size" in inputs: new_workflow[latent_id]["inputs"]["batch_size"] = inputs["batch_size"]

    # Load Image (for I2I / I2V)
    load_image_id = None
    if "11" in new_workflow and new_workflow["11"]["class_type"] == "LoadImage": load_image_id = "11"
    elif "4" in new_workflow and new_workflow["4"]["class_type"] == "LoadImage": load_image_id = "4"

    if load_image_id and "image_filename" in inputs:
        new_workflow[load_image_id]["inputs"]["image"] = inputs["image_filename"]

    return new_workflow
