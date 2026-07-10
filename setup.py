from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(name='plaque-toolkit',
      version='1.0.5',
      description='Bacteriophage plaque size & turbidity measurement toolkit '
                  '(built on the Plaque Size Tool, Trofimova & Jaschke 2021, Apache-2.0)',
      long_description=long_description,
      long_description_content_type='text/markdown',
      url='https://github.com/mbaffour/plaque-toolkit',
      author='Michael Baffour Awuah',
      license='Apache-2.0',
      install_requires=['numpy<2', 'opencv-python', 'imutils', 'pandas', 'Pillow'],
      py_modules=['plaque_size_tool'],
      zip_safe=False,
      keywords='bacteriophage phage virus viral plaque size turbidity')