import typer
import pathlib
import re
import subprocess
import getpass
import yaml
import toml
import os
from rich import print

app = typer.Typer()

# Internal functions

def generate_templatte(dictionary, parent_key='', sep='.'):
    items = []
    for key, value in dictionary.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, dict):
            items.extend(generate_templatte(value, new_key, sep=sep).items())
        else:
            items.append((new_key, f"{{{{{new_key}}}}}"))
    return dict(items)

def generate_toml_templatte(toml_file):
    with open(toml_file, 'r') as f:
        toml_data = toml.load(f)
    return generate_templatte(toml_data)

def cypher(templatte_file:str='templatte.toml'):
    if not os.path.exists(templatte_file):
        print(f'ERROR: {templatte_file} does not exist')
        return 1
    # Read passphrase
    print("Set a passphrase and save it in your secret manager. Don't loose it. It would be neccessary for decription")
    passphrase = getpass.getpass("Passphrase:")
    passphrase2 = getpass.getpass("Passphrase:")

    if passphrase != passphrase2:
        raise ValueError("Passphrases not identical!")

    # Perform encryption
    print("Encrypting...")

    args = [
    "gpg",
    "--batch",
    "--passphrase-fd", "0",
    "--output", f'{templatte_file}.gpg',
    "--symmetric",
    "--yes",
    "--cipher-algo", "AES256",
    templatte_file,
    ]

    result = subprocess.run(
    args, input=passphrase.encode(),
    capture_output=True)

    if result.returncode != 0:
        raise ValueError(result.stderr)
    else:
        if os.path.exists(templatte_file):
            # Delete the file
            os.remove(templatte_file)

def decypher(templatte_file:str='templatte.toml'):
    if not os.path.exists(f'{templatte_file}.gpg'):
        print(f'ERROR: {templatte_file} does not exist')
        return 1
    passphrase = getpass.getpass("Passphrase:")
    # decrypt
    args = [
    "gpg",
    "--passphrase-fd", "0",
    "--output", templatte_file,
    "--decrypt",
    f'{templatte_file}.gpg',
    ]

    result = subprocess.run(
    args, input=passphrase.encode(),
    capture_output=True)

    if result.returncode != 0:
        raise ValueError(result.stderr)
    else:
        if os.path.exists(f'{templatte_file}.gpg'):
            # Delete the file
            os.remove(f'{templatte_file}.gpg')

def read_toml_file(file_path):
    """
    Reads a TOML file and returns its content as a dictionary.

    Parameters
    ----------
    file_path : str
        The path of the TOML file to read.

    Returns
    -------
    dict
        A dictionary representing the content of the TOML file.
    """
    with open(file_path, 'r') as f:
        return toml.load(f)

def generate_value_structure(data, parent_key='', sep='.'):
    """
    Generates a value structure and a template structure based on a TOML data dictionary.

    Parameters
    ----------
    data : dict
        The dictionary representing the TOML data structure.
    parent_key : str, optional
        The parent key used in recursion.
    sep : str, optional
        The separator used for key generation.

    Returns
    -------
    tuple
        A tuple of two elements:
            - A dictionary representing the value structure.
            - A dictionary representing the template structure.
    """
    value_structure = {}
    template_structure = {}

    for key, value in data.items():
        current_key = f"{parent_key}{sep}{key}" if parent_key else key

        if isinstance(value, dict):
            sub_value_structure, sub_template_structure = generate_value_structure(value, current_key, sep)
            value_structure.update(sub_value_structure)
            template_structure[current_key] = "{{{" + current_key + "}}}"
            template_structure.update(sub_template_structure)
        else:
            value_structure[current_key] = value
            template_structure[current_key] = "{{{" + current_key + "}}}"

    return value_structure, template_structure

def generate_template_structure(data, parent_key='', sep='.'):
    """
    Generates a template structure based on a TOML data dictionary.

    Parameters
    ----------
    data : dict
        The dictionary representing the TOML data structure.
    parent_key : str, optional
        The parent key used in recursion.
    sep : str, optional
        The separator used for key generation.

    Returns
    -------
    dict
        A dictionary representing the template structure.
    """
    template_structure = {}

    for key, value in data.items():
        current_key = f"{parent_key}{sep}{key}" if parent_key else key

        if isinstance(value, dict):
            sub_template_structure = generate_template_structure(value, current_key, sep)
            template_structure.update(sub_template_structure)
        else:
            template_structure[current_key] = f"{{{{{current_key}}}}}"

    return template_structure

def write_template_structure_to_file(template_structure, file_path):
    """
    Writes the template structure to a text file.

    Parameters
    ----------
    template_structure : dict
        The template structure to write to the file.
    file_path : str
        The path of the file where the template structure will be written.

    Returns
    -------
    None
    """
    with open(file_path, 'w') as f:
        for key, value in template_structure.items():
            f.write(f"{key} = {value}\n")

def write_value_structure_to_file(value_structure, file_path):
    """
    Writes the value structure to a TOML file.

    Parameters
    ----------
    value_structure : dict
        The value structure to write to the file.
    file_path : str
        The path of the file where the value structure will be written.

    Returns
    -------
    None
    """
    original_data = {}
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            original_data = toml.load(file)

    merged_data = {**original_data, **value_structure}
    sorted_merged_data = {key: merged_data[key] for key in sorted(merged_data)}

    with open(file_path, 'w') as file:
        toml.dump(sorted_merged_data, file)

def process_toml_files(workspace_dir):
    """
    Processes TOML files within a directory and generates value and template files.

    Parameters
    ----------
    workspace_dir : str
        The working directory containing the TOML files.
    output_dir : str
        The output directory where value and template files will be generated.

    Returns
    -------
    None
    """
    all_values = {}
    excepted_files = ['templatte.toml', 'pyproject.toml']
    for root, dirs, files in os.walk(workspace_dir):
        for file in files:
            if file in excepted_files:
                continue

            if file.endswith(".toml"):
                file_path = os.path.join(root, file)
                print(f"Processing file: {file_path}")
                toml_data = read_toml_file(file_path)
                value_structure, _ = generate_value_structure(toml_data)
                file_values = {f"{file_path}_{key}": value for key, value in value_structure.items()}
                all_values.update(file_values)
                template_structure = generate_template_structure(toml_data)
                write_template_structure_to_file(template_structure, os.path.join(workspace_dir, f"{file_path}.latte"))

    write_value_structure_to_file(all_values, os.path.join(workspace_dir, "templatte.toml"))

def process_latte_files(workspace_dir):
    """
    Processes LATTE files within a directory and remove original valued config file.

    Parameters
    ----------
    workspace_dir : str
        The working directory containing the LATTE files.

    Returns
    -------
    None
    """
    excepted_files = ['templatte.toml', 'pyproject.toml']
    for root, dirs, files in os.walk(workspace_dir):
        for file in files:
            if file in excepted_files:
                continue
            if file.endswith(".latte"):
                file_path = os.path.join(root, file.split('.latte')[0])
                if os.path.exists(file_path):
                    print(f"Removing file: {file_path}")
                    os.remove(file_path)
              
def read_template_file(template_file_path):
    """
    Reads a template file and loads its content into a Python dictionary.

    Parameters
    ----------
    template_file_path : str
        The path of the template file to read.

    Returns
    -------
    dict
        A dictionary representing the template structure.
    """
    # Read the template file (Ta.toml)
    with open(template_file_path, 'r') as f:
        lines = f.readlines()

    # Convert the template file lines into a dictionary
    template_structure = {}
    for line in lines:
        if '=' in line:
            key, value = line.strip().split(' = ')
            template_structure[key] = value
    return template_structure

def restore_original_toml(value_file_path, template_files_dir='.'):
    """
    Restores the original structure of TOML data using a value file and template files.

    Parameters
    ----------
    value_file_path : str
        The path of the value file.
    template_files_dir : str
        The directory containing the template files.

    Returns
    -------
    list
        A list of original TOML data structures.
    """
    # Read the value file (Va.toml)
    with open(value_file_path, 'r') as f:
        value_data = toml.load(f)
    original_structures = []
    # Iterate through template files
    for root, _, files in os.walk(template_files_dir):
        for file in files:
            if file.endswith(".toml.latte"):
                file_path = os.path.join(root, file)
                # Leer el archivo de plantillas correspondiente
                template_data = read_template_file(file_path)
                # Generar el archivo TOML original utilizando el archivo de valores y la plantilla
                original_data = {}

                for key, template in template_data.items():
                    keys = key.split('.')
                    current_dict = original_data
                    for k in keys[:-1]:
                        if k not in current_dict:
                            current_dict[k] = {}
                        current_dict = current_dict[k]
                    file_name = file_path.split('.latte', 1)[0]
                    current_dict[keys[-1]] = value_data[f'{file_name}_{key}'.strip()]
                write_value_structure_to_file(original_data, file_path.split('.latte', 1)[0])
                if os.path.exists(file_path):
                    # Delete the file
                    os.remove(file_path)
                original_structures.append(original_data)

    return original_structures

@app.callback()
def callback():
    """
    Welcome to Templatte, where crafting configuration files is as delightful as brewing your favorite coffee.

    """

@app.command() 
def genelatte(config_type:str='toml'):
    """
    Searchs recursively for any config file in the workspace (just toml for now) and generates latte files (templatte) and values file (templatte.toml)
    """
    process_toml_files('.')

@app.command() 
def press():
    """
    Cypher templatte values with a passphrase
    """
    cypher()

@app.command()
def pour():
    """
    Decypher templatte values with a passphrase and populates
    """
    decypher()

@app.command()
def grind():
    """
    Searchs recursively for any latte file in the workspace and removes the original valued config file associated
    """
    process_latte_files('.')

@app.command()
def deploy():
    """
    Populates configs templates files parsing templatte.toml values
    """
    original_structures = restore_original_toml('templatte.toml')
    print(original_structures)

if __name__ == "__main__":
    app()