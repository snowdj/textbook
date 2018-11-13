from subprocess import check_call
import os
import os.path as op
import shutil as sh
import yaml
from nbclean import NotebookCleaner
import nbformat as nbf
from tqdm import tqdm
import numpy as np
from glob import glob
import argparse
import string
DESCRIPTION = ("Convert a collection of Jupyter Notebooks into Jekyll "
               "markdown suitable for a course textbook.")

parser = argparse.ArgumentParser(description=DESCRIPTION)
parser.add_argument("--site_root", default=None, help="Path to the root of the textbook repository.")
parser.add_argument("--path-template", default=None, help="Path to the template nbconvert uses to build markdown files")
parser.add_argument("--path-config", default=None, help="Path to the Jekyll configuration file")
parser.add_argument("--path-toc", default=None, help="Path to the Table of Contents YAML file")
parser.add_argument("--overwrite", action='store_true', help="Overwrite md files if they already exist.")
parser.add_argument("--execute", action='store_true', help="Execute notebooks before converting to MD.")
parser.set_defaults(overwrite=False, execute=False)

# Defaults
BUILD_FOLDER_NAME = "_build"
SUPPORTED_FILE_SUFFIXES = ['.ipynb', '.md']
ALLOWED_CHARACTERS = string.ascii_letters + '-_/.' + string.digits

def _check_url_page(url_page):
    """Check that the page URL matches certain conditions."""
    if not all(ii in ALLOWED_CHARACTERS for ii in url_page):
        raise ValueError("Found unsupported character in filename: {}".format(url_page))
    if '.' in os.path.splitext(url_page)[-1]:
        raise _error("A toc.yml entry links to a file directly. You should strip the file suffix.\n"
                        "Please change {} to {}".format(url_page, os.path.splitext(url_page)[0]))
    if any(url_page.startswith(ii) for ii in [CONTENT_FOLDER_NAME, os.sep+CONTENT_FOLDER_NAME]):
        raise ValueError("It looks like you have a page URL that starts with your content folder's name."
                            "page URLs should be *relative* to the content folder. Here is the page URL: {}".format(url_page))
    
def _prepare_toc(toc):
    """Prepare the TOC for processing."""
    # Drop toc items w/o links
    toc = [ii for ii in toc if ii.get('url', None) is not None]
    # Un-nest the TOC so it's a flat list
    new_toc = []
    for ii in toc:
        sections = ii.pop('sections', None)
        new_toc.append(ii)
        if sections is None:
            continue
        for jj in sections:
            subsections = jj.pop('subsections', None)
            new_toc.append(jj)
            if subsections is None:
                continue
            for kk in subsections:
                new_toc.append(kk)
    return new_toc


def _prepare_url(url):
    """Prep the formatting for a url."""
    # Strip suffixes and prefixes of the URL
    if not url.startswith('/'):
        url = '/' + url

    # Standardize the quotes character
    url = url.replace('"', "'")
    return url


def _clean_notebook_cells(path_ntbk):
    """Clean up cell text of an nbformat NotebookNode."""
    ntbk = nbf.read(path_ntbk, nbf.NO_CONVERT)
    # Remove '#' from the end of markdown headers
    for cell in ntbk.cells:
        if cell.cell_type == "markdown":
            cell_lines = cell.source.split('\n')
            for ii, line in enumerate(cell_lines):
                if line.startswith('#'):
                    cell_lines[ii] = line.rstrip('#').rstrip()
            cell.source = '\n'.join(cell_lines)
    nbf.write(ntbk, path_ntbk)


def _clean_lines(lines, filepath):
    """Replace images with jekyll image root and add escape chars as needed."""
    inline_replace_chars = ['#']
    # Images: replace absolute nbconvert image paths to baseurl paths
    path_rel_root = op.relpath(PATH_SITE_ROOT, op.dirname(filepath))
    path_rel_root_one_up = path_rel_root.replace('../', '', 1)
    for ii, line in enumerate(lines):
        # Handle relative paths because we remove `content/` from the URL
        # If there's a path that goes back to the root, remove a level`
        # This is for images referenced directly in the markdown
        if path_rel_root in line:
            line = line.replace(path_rel_root, path_rel_root_one_up)
        # For programmatically-generated images from notebooks, replace the abspath with relpath
        line = line.replace(PATH_IMAGES_FOLDER, op.relpath(PATH_IMAGES_FOLDER, op.dirname(filepath)))

        # Adding escape slashes since Jekyll removes them when it serves the page
        # Make sure we have at least two dollar signs and they
        # Aren't right next to each other
        dollars = np.where(['$' == char for char in line])[0]
        if len(dollars) > 2 and all(ii > 1 for ii in (dollars[1:] - dollars[:1])):
            for char in inline_replace_chars:
                line = line.replace('\\{}'.format(char), '\\\\{}'.format(char))
        line = line.replace(' \\$', ' \\\\$')
        lines[ii] = line
    return lines


def _copy_non_content_files():
    """Copy non-markdown/notebook files in the content folder into build folder so relative links work."""
    all_files = glob(op.join(PATH_CONTENT_FOLDER, '**', '*'), recursive=True)
    non_content_files = [ii for ii in all_files if not any(ii.endswith(ext) for ext in SUPPORTED_FILE_SUFFIXES)]
    for ifile in non_content_files:
        if op.isdir(ifile):
            continue

        # The folder name may change if the permalink sanitizing changes it.
        # this ensures that a new folder exists if needed
        new_path = ifile.replace(os.sep + CONTENT_FOLDER_NAME, os.sep + BUILD_FOLDER_NAME)
        if not op.isdir(op.dirname(new_path)):
            os.makedirs(op.dirname(new_path))
        sh.copy2(ifile, new_path)

def _error(msg):
    msg = '\n\n==========\n{}\n==========\n'.format(msg)
    raise ValueError(msg)


if __name__ == '__main__':
    ###############################################################################
    # Default values and arguments

    args = parser.parse_args()
    overwrite = bool(args.overwrite)
    execute = bool(args.execute)
    if args.site_root is None:
        args.site_root = op.join(op.dirname(op.abspath(__file__)), '..')

    # Paths for our notebooks
    PATH_SITE_ROOT = op.abspath(args.site_root)

    PATH_TOC_YAML = args.path_toc if args.path_toc is not None else op.join(PATH_SITE_ROOT, '_data', 'toc.yml')
    CONFIG_FILE = args.path_config if args.path_config is not None else op.join(PATH_SITE_ROOT, '_config.yml')
    PATH_TEMPLATE = args.path_template if args.path_template is not None else op.join(PATH_SITE_ROOT, 'scripts', 'templates', 'jekyllmd.tpl')
    PATH_IMAGES_FOLDER = op.join(PATH_SITE_ROOT, '_build', 'images')
    BUILD_FOLDER = op.join(PATH_SITE_ROOT, BUILD_FOLDER_NAME)

    ###############################################################################
    # Read in textbook configuration

    # Load the yaml for this site
    with open(CONFIG_FILE, 'r') as ff:
        site_yaml = yaml.load(ff.read())
    CONTENT_FOLDER_NAME = site_yaml.get('content_folder_name').strip('/')
    PATH_CONTENT_FOLDER = op.join(PATH_SITE_ROOT, CONTENT_FOLDER_NAME)

    # Load the textbook yaml for this site
    if not op.exists(PATH_TOC_YAML):
        _error("No toc.yml file found, please create one")
    with open(PATH_TOC_YAML, 'r') as ff:
        toc = yaml.load(ff.read())

    # Drop divider items and non-linked pages in the sidebar, un-nest sections
    toc = _prepare_toc(toc)

    ###############################################################################
    # Generating the Jekyll files for all content

    n_skipped_files = 0
    n_built_files = 0
    print("Convert and copy notebook/md files...")
    for ix_file, page in enumerate(tqdm(list(toc))):
        url_page = page.get('url', None)
        title = page.get('title', None)

        # Make sure URLs (file paths) have correct structure
        _check_url_page(url_page)

        ###############################################################################
        # Create path to old/new file and create directory

        # URL will be relative to the CONTENT_FOLDER
        path_url_page = os.path.join(PATH_CONTENT_FOLDER, url_page.lstrip('/'))
        path_url_folder = os.path.dirname(path_url_page)

        # URLs shouldn't have the suffix in there already so now we find which one to add
        for suf in SUPPORTED_FILE_SUFFIXES:
            if op.exists(path_url_page + suf):
                path_url_page = path_url_page + suf
                break

        if not op.exists(path_url_page):
            raise _error("Could not find file called {} with any of these extensions: {}".format(path_url_page, SUPPORTED_FILE_SUFFIXES))

        # Create and check new folder / file paths
        path_new_folder = path_url_folder.replace(os.sep + CONTENT_FOLDER_NAME, os.sep + BUILD_FOLDER_NAME)
        path_new_file = op.join(path_new_folder, op.basename(path_url_page).replace('.ipynb', '.md'))

        if overwrite is False and op.exists(path_new_file):
            n_skipped_files += 1
            continue

        if not op.isdir(path_new_folder):
            os.makedirs(path_new_folder)

        ###############################################################################
        # Generate previous/next page URLs
        if ix_file == 0:
            url_prev_page = ''
            prev_file_title = ''
        else:
            prev_file_title = toc[ix_file-1].get('title')
            url_prev_page = toc[ix_file-1].get('url')
            url_prev_page = _prepare_url(url_prev_page)

        if ix_file == len(toc) - 1:
            url_next_page = ''
            next_file_title = ''
        else:
            next_file_title = toc[ix_file+1].get('title')
            url_next_page = toc[ix_file+1].get('url')
            url_next_page = _prepare_url(url_next_page)

        ###############################################################################
        # Content conversion

        # Convert notebooks or just copy md if no notebook.
        if path_url_page.endswith('.ipynb'):
            # Create a temporary version of the notebook we can modify
            tmp_notebook = path_url_page + '_TMP'
            sh.copy2(path_url_page, tmp_notebook)

            ###############################################################################
            # Notebook cleaning

            # Clean up the file before converting
            cleaner = NotebookCleaner(tmp_notebook)
            cleaner.remove_cells(empty=True)
            if site_yaml.get('hide_cell_text', False):
                cleaner.remove_cells(search_text=site_yaml.get('hide_cell_text'))
            if site_yaml.get('hide_code_text', False):
                cleaner.clear(kind="content", search_text=site_yaml.get('hide_code_text'))
            cleaner.clear('stderr')
            cleaner.save(tmp_notebook)
            _clean_notebook_cells(tmp_notebook)

            ###############################################################################
            # Conversion to Jekyll Markdown

            # Run nbconvert moving it to the output folder
            # This is the output directory for `.md` files
            build_call = '--FilesWriter.build_directory={}'.format(path_new_folder)
            # Copy notebook output images to the build directory using the base folder name
            path_after_build_folder = path_new_folder.split(os.sep + BUILD_FOLDER_NAME + os.sep)[-1]
            nb_output_folder = op.join(PATH_IMAGES_FOLDER, path_after_build_folder)
            images_call = '--NbConvertApp.output_files_dir={}'.format(nb_output_folder)
            call = ['jupyter', 'nbconvert', '--log-level="CRITICAL"',
                    '--to', 'markdown', '--template', PATH_TEMPLATE,
                    images_call, build_call, tmp_notebook]
            if execute is True:
                call.insert(-1, '--execute')

            check_call(call)
            os.remove(tmp_notebook)
        elif path_url_page.endswith('.md'):
            # If a non-notebook file, just copy it over.
            # If markdown we'll add frontmatter later
            sh.copy2(path_url_page, path_new_file)
        else:
            raise _error("Files must end in ipynb or md. Found file {}".format(path_url_page))

        ###############################################################################
        # Modify the generated Markdown to work with Jekyll

        # Clean markdown for Jekyll quirks (e.g. extra escape characters)
        with open(path_new_file, 'r') as ff:
            lines = ff.readlines()
        lines = _clean_lines(lines, path_new_file)

        # Front-matter YAML
        yaml_fm = []
        yaml_fm += ['---']
        yaml_fm += ['redirect_from:']
        yaml_fm += ['  - "{}"'.format(_prepare_url(url_page).replace('_', '-').lower())]
        if ix_file == 0:
            yaml_fm += ['  - "/"']
        if path_url_page.endswith('.ipynb'):
            interact_path = 'content/' + path_url_page.split('content/')[-1]
            yaml_fm += ['interact_link: {}'.format(interact_path)]
        yaml_fm += ["title: '{}'".format(title)]
        yaml_fm += ['prev_page:']
        yaml_fm += ['  url: {}'.format(url_prev_page)]
        yaml_fm += ["  title: '{}'".format(prev_file_title)]
        yaml_fm += ['next_page:']
        yaml_fm += ['  url: {}'.format(url_next_page)]
        yaml_fm += ["  title: '{}'".format(next_file_title)]
        yaml_fm += ['comment: "***PROGRAMMATICALLY GENERATED, DO NOT EDIT. SEE ORIGINAL FILES IN /{}***"'.format(CONTENT_FOLDER_NAME)]
        yaml_fm += ['---']
        yaml_fm = [ii + '\n' for ii in yaml_fm]
        lines = yaml_fm + lines

        # Write the result
        with open(path_new_file, 'w') as ff:
            ff.writelines(lines)
        n_built_files += 1

    ###############################################################################
    # Finishing up...

    # Copy non-markdown files in notebooks/ in case they're referenced in the notebooks
    print('Copying non-content files inside `{}/`...'.format(CONTENT_FOLDER_NAME))
    _copy_non_content_files()

    # Message at the end
    print("\n===========")
    print("Generated {} new files\nSkipped {} already-built files".format(n_built_files, n_skipped_files))
    if n_built_files == 0:
        print("Delete the markdown files in '{}' for any pages that you wish to re-build.".format(BUILD_FOLDER_NAME))
    print("\nYour Jupyter Book is now in `{}/`.".format(BUILD_FOLDER_NAME))
    print("\nDemo your Jupyter book with `make serve` or push to GitHub!")

    print('===========\n')

