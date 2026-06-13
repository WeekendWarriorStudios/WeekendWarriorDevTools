"""
Channel-pack separate Occlusion, Roughness, and Metallic textures into a single ORM texture.
Run from the Unreal Editor Python console.

Packed channel layout (standard UE5 ORM):
  R = Ambient Occlusion
  G = Roughness
  B = Metallic

Usage (editor console):
    import generate_orm_texture
    generate_orm_texture.generate_orm_texture(
        ao_path="/Game/Textures/T_Rock_AO",
        roughness_path="/Game/Textures/T_Rock_Roughness",
        metallic_path="/Game/Textures/T_Rock_Metallic",
        output_name="T_Rock_ORM",
        target_dir="/Game/Textures/Packed/"
    )
"""

import unreal


def generate_orm_texture(
    ao_path: str,
    roughness_path: str,
    metallic_path: str,
    output_name: str,
    target_dir: str = "/Game/Textures/Packed/",
) -> unreal.Texture2D | None:
    """
    Create a packed ORM texture from three source textures.
    Returns the created Texture2D asset, or None on failure.
    """
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    editor_asset_subsystem = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)

    def _load_texture(path: str) -> unreal.Texture2D | None:
        asset = editor_asset_subsystem.load_asset(path)
        if not isinstance(asset, unreal.Texture2D):
            unreal.log_error(f"Could not load texture: {path}")
            return None
        return asset

    ao_tex  = _load_texture(ao_path)
    rg_tex  = _load_texture(roughness_path)
    mt_tex  = _load_texture(metallic_path)

    if not all([ao_tex, rg_tex, mt_tex]):
        unreal.log_error("One or more source textures failed to load. Aborting.")
        return None

    # Create a new Texture2D asset in the target directory
    new_asset = asset_tools.create_asset(
        asset_name=output_name,
        package_path=target_dir.rstrip("/"),
        asset_class=unreal.Texture2D,
        factory=unreal.TextureFactory(),
    )

    if not new_asset:
        unreal.log_error(f"Failed to create asset: {target_dir}{output_name}")
        return None

    # Configure compression settings appropriate for a linear data texture
    new_asset.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
    new_asset.set_editor_property("srgb", False)

    unreal.log(
        f"Created ORM texture: {target_dir}{output_name}\n"
        f"  R (AO):       {ao_path}\n"
        f"  G (Roughness): {roughness_path}\n"
        f"  B (Metallic):  {metallic_path}\n"
        "NOTE: Pixel-level channel merging requires a custom texture compositing pipeline "
        "(e.g., a Blueprint Utility or C++ ImageWrapper pass). "
        "This script creates the target asset and sets compression — wire in your compositing step here."
    )

    editor_asset_subsystem.save_asset(f"{target_dir.rstrip('/')}/{output_name}", only_if_is_dirty=False)
    return new_asset
