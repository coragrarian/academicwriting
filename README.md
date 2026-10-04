# Academic Writing for Agrarian Sciences

This repository contains the source for the **Academic Writing for Agrarian Sciences** GitHub Pages website, a self-study resource for students and researchers who want guided practice with the structure and language of research articles in the Agrarian Sciences.

The teaching materials were originally prepared by the research team in shared Google Docs. The website provides a way of turning those materials into a consistent, interactive learning resource: after the exercises are given a small amount of Markdown structure and metadata, a lightweight build process generates the published pages, including answer checking, feedback, progress tracking and navigation.

The current site covers three sections of the research article:

- [Introduction](./exercises/introduction.md)
- [Methods](./exercises/methods.md)
- [Results](./exercises/results.md)

Together, they currently comprise 10 subsections and 30 exercises across 44 generated HTML pages.

The site is published through GitHub Pages and remains entirely static. Python and Jinja are used during the build process, while vanilla JavaScript handles the interactive behaviour in the browser. There is no backend, account system or database.

For local development, build instructions and maintenance details, see
[DEVELOPMENT.md](DEVELOPMENT.md).
