import argostranslate.package
import argostranslate.translate
import sys

def setup_argos():
    print("Updating package index...")
    argostranslate.package.update_package_index()
    available_packages = argostranslate.package.get_available_packages()
    
    # Install TR -> EN
    print("Looking for TR -> EN package...")
    package_to_install = next(
        filter(
            lambda x: x.from_code == "tr" and x.to_code == "en", available_packages
        ), None
    )
    if package_to_install:
        print(f"Installing {package_to_install.from_code} to {package_to_install.to_code}...")
        argostranslate.package.install_from_path(package_to_install.download())
    else:
        print("TR to EN package not found!")

    # Install EN -> TR
    print("Looking for EN to TR package...")
    package_to_install_en_tr = next(
        filter(
            lambda x: x.from_code == "en" and x.to_code == "tr", available_packages
        ), None
    )
    if package_to_install_en_tr:
        print(f"Installing {package_to_install_en_tr.from_code} to {package_to_install_en_tr.to_code}...")
        argostranslate.package.install_from_path(package_to_install_en_tr.download())
    else:
        print("EN to TR package not found!")

    print("Installation complete.")

def test_translation():
    print("Testing translation...")
    try:
        # Test EN -> TR
        text_en = "Hello World"
        translated_tr = argostranslate.translate.translate(text_en, "en", "tr")
        print(f"EN->TR: '{text_en}' -> '{translated_tr}'")
        
        # Test TR -> EN
        text_tr = "Merhaba Dünya"
        translated_en = argostranslate.translate.translate(text_tr, "tr", "en")
        print(f"TR->EN: '{text_tr}' -> '{translated_en}'")
        
    except Exception as e:
        print(f"Translation failed: {e}")

if __name__ == "__main__":
    setup_argos()
    test_translation()
