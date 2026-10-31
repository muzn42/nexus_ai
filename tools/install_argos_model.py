import argostranslate.package
import os

model_path = "translate-en_tr-1_5.argosmodel"

if os.path.exists(model_path):
    print(f"Installing {model_path}...")
    argostranslate.package.install_from_path(model_path)
    print("Installation successful!")
    
    # Verify installation
    installed_languages = argostranslate.package.get_installed_packages()
    print("Installed packages:")
    for pkg in installed_languages:
        print(f"- {pkg}")
else:
    print(f"File not found: {model_path}")
