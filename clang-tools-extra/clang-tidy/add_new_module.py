#!/usr/bin/env python3
#
# ===- add_new_module.py - clang-tidy module generator -------*- python -*--===#
#
# Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# ===-----------------------------------------------------------------------===#

import argparse
import io
import itertools
import os
import re
import sys
import textwrap

# FIXME Python 3.9: Replace typing.Tuple with builtins.tuple.
from typing import Optional, Tuple, Match


# Creates a boilerplate CMakelist file if missing.
def write_cmake(module_path: str, module_camel: str) -> None:
    filename = os.path.join(module_path, "CMakeLists.txt")
    if os.path.exists(filename):
        return

    print("Creating %s..." % filename)
    with io.open(filename, "w", encoding="utf8", newline="\n") as f:
        f.write(
            """\
set(LLVM_LINK_COMPONENTS
  FrontendOpenMP
  Support
  )

add_clang_library(%(clang_library_name)s STATIC
  %(module_cpp)s

  LINK_LIBS
  clangTidy
  clangTidyUtils

  DEPENDS
  omp_gen
  ClangDriverOptions
  )

clang_target_link_libraries(%(clang_library_name)s
  PRIVATE
  clangAnalysis
  clangAST
  clangASTMatchers
  clangBasic
  clangLex
  )
"""
            % {
                "clang_library_name": "clangTidy%sModule" % module_camel,
                "module_cpp": "%sTidyModule.cpp" % module_camel,
            }
        )


# Adds the implementation of the new module.
def write_module_cpp(
    module_path: str, module: str, module_camel: str, namespace: str,
) -> None:
    filename = os.path.join(module_path, "%sTidyModule.cpp" % module_camel)
    if os.path.exists(filename):
        print("File already exists: %s" % filename)
        return
    print("Creating %s..." % filename)
    with io.open(filename, "w", encoding="utf8", newline="\n") as f:
        f.write("//===--- ")
        f.write(os.path.basename(filename))
        f.write(" - clang-tidy ")
        f.write("-" * max(0, 51 - len(os.path.basename(filename))))
        f.write("-===//")
        f.write(
            """
//
// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.
// See https://llvm.org/LICENSE.txt for license information.
// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
//
//===----------------------------------------------------------------------===//

#include "../ClangTidy.h"
#include "../ClangTidyModule.h"
#include "../ClangTidyModuleRegistry.h"

namespace clang::tidy {
namespace %(namespace)s {

class %(class_name)s : public ClangTidyModule {
public:
  void addCheckFactories(ClangTidyCheckFactories &CheckFactories) override {
  }
};

} // namespace %(namespace)s

// Register the %(class_name)s using this statically initialized variable.
static ClangTidyModuleRegistry::Add<%(namespace)s::%(class_name)s>
    X("%(module)s-module", "Adds %(module)s-specific lint checks.");

// This anchor is used to force the linker to link in the generated object file
// and thus register the %(class_name)s.
volatile int %(class_name)sAnchorSource = 0;

} // namespace clang::tidy
"""
            % {
                "namespace": namespace,
                "class_name": "%sModule" % module_camel,
                "module": module,
            }
        )


def update_clang_tidy_cmake(
    clang_tidy_path: str, module: str, module_camel: str,
) -> None:
    cmake_path = os.path.join(clang_tidy_path, "CMakeLists.txt")
    with io.open(cmake_path, "r", encoding="utf8") as f:
        lines = f.readlines()

    linesout = []

    i, j = 0, 0
    while j < len(lines) and not lines[j].startswith("add_subdirectory("):
        j += 1

    linesout.extend(lines[i:j])

    add_subdirectory_line = "add_subdirectory(%s)\n" % module

    i = j
    while j < len(lines):
        if lines[j].startswith("if("):
            while j < len(lines):
                if lines[j].startswith("endif()"):
                    j += 1
                    break
                j += 1
            continue

        if lines[j].startswith("set(ALL_CLANG_TIDY_CHECKS"):
            break
        if lines[j] == add_subdirectory_line:
            add_subdirectory_line = ""  # Line exists, do not add again.
            break
        if lines[j] >= add_subdirectory_line:
            break
        j += 1

    linesout.extend(lines[i:j])

    if add_subdirectory_line:
        linesout.append(add_subdirectory_line)

    i = j
    while j < len(lines):
        if lines[j].startswith("set(ALL_CLANG_TIDY_CHECKS"):
            j += 1
            break
        j += 1
    linesout.extend(lines[i:j])

    clang_library_line = "  clangTidy%sModule\n" % module_camel

    i = j
    while j < len(lines):
        if ")" in lines[j]:
            break
        if lines[j] == clang_library_line:
            clang_library_line = ""  # Line exists, do not add again.
            break
        if lines[j] >= clang_library_line:
            break
        j += 1

    linesout.extend(lines[i:j])

    if clang_library_line:
        linesout.append(clang_library_line)

    linesout.extend(lines[j:])

    if lines == linesout:
        print("Module already included: %s" % cmake_path)
        return

    print("Updating %s..." % cmake_path)
    with io.open(cmake_path, "w", encoding="utf8", newline="\n") as f:
        for line in linesout:
            f.write(line)


def update_clang_tidy_force_linker(
    clang_tidy_path: str, module_camel: str,
):
    header_path = os.path.join(clang_tidy_path, "ClangTidyForceLinker.h")
    with io.open(header_path, "r", encoding="utf8") as f:
        lines = f.readlines()

    linesout = []

    link_lines = [
        "// This anchor is used to force the linker to link the %sModule.\n" % module_camel,
        "extern volatile int %sModuleAnchorSource;\n" % module_camel,
        "static int LLVM_ATTRIBUTE_UNUSED %sModuleAnchorDestination =\n" % module_camel,
        "    %sModuleAnchorSource;\n" % module_camel,
        "\n",
    ]

    anchor_comment = "// This anchor "

    i, j = 0, 0
    while j < len(lines) and not lines[j].startswith(anchor_comment):
        j += 1

    while j < len(lines):
        if lines[j].startswith("#if"):
            while j < len(lines):
                if lines[j].startswith("#endif"):
                    j += 1
                    break
                j += 1
            continue

        if lines[j].startswith("} // namespace"):
            break

        if not lines[j].startswith(anchor_comment):
            j += 1
            continue

        if lines[j] == link_lines[0]:
            link_lines = []  # Link already exists, do not add again.
            break
        if lines[j] >= link_lines[0]:
            break

        j += 1

    linesout.extend(lines[i:j])

    if link_lines:
        linesout.extend(link_lines)

    linesout.extend(lines[j:])

    if lines == linesout:
        print("Module already has forced link: %s" % header_path)
        return

    print("Updating %s..." % header_path)
    with io.open(header_path, "w", encoding="utf8", newline="\n") as f:
        for line in linesout:
            f.write(line)


def get_camel_name(check_name: str) -> str:
    return "".join(map(lambda elem: elem.capitalize(), check_name.split("-")))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--description",
        "-d",
        help="short description of what the module is about",
        default="FIXME: Write a short description",
        type=str,
    )
    parser.add_argument(
        "module",
        nargs="?",
        help="module directory for new tidy checks (e.g., misc)",
    )
    args = parser.parse_args()

    if not args.module:
        print("Module must be specified.")
        parser.print_usage()
        return

    if not args.module.isalnum():
        print("Module name must be alphanumeric: %s" % args.module)
        return

    module = args.module
    module_camel = get_camel_name(module)
    clang_tidy_path = os.path.dirname(sys.argv[0])
    module_path = os.path.join(clang_tidy_path, module)

    if os.path.exists(module_path):
        print("Module path already exists: %s" % module_path)
    else:
        print("Creating %s..." % module_path)
        os.mkdir(module_path)

    write_cmake(module_path, module_camel)
    write_module_cpp(module_path, module, module_camel, module)

    docs_path = os.path.join(clang_tidy_path, "..", "docs", "clang-tidy", "checks", module)
    if os.path.exists(docs_path):
        print("Docs path already exists: %s" % docs_path)
    else:
        print("Creating %s..." % docs_path)
        os.mkdir(docs_path)

    test_path = os.path.join(clang_tidy_path, "..", "test", "clang-tidy", "checkers", module)
    if os.path.exists(test_path):
        print("Test path already exists: %s" % test_path)
    else:
        print("Creating %s..." % test_path)
        os.mkdir(test_path)

    update_clang_tidy_cmake(clang_tidy_path, module, module_camel)
    update_clang_tidy_force_linker(clang_tidy_path, module_camel)
    print("Done. Now it's your turn!")


if __name__ == "__main__":
    main()
