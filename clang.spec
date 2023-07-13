%bcond_without sys_llvm
%bcond_without check

%global maj_ver 15
%global min_ver 0
%global patch_ver 7
%global clang_version %{maj_ver}.%{min_ver}.%{patch_ver}

%if %{with sys_llvm}
%global pkg_name clang
%global install_prefix %{_prefix}
%else
%global pkg_name clang%{maj_ver}
%global install_prefix %{_libdir}/llvm%{maj_ver}
%endif

%global install_bindir %{install_prefix}/bin
%global install_includedir %{install_prefix}/include
%if 0%{?__isa_bits} == 64
%global install_libdir %{install_prefix}/lib64
%else
%global install_libdir %{install_prefix}/lib
%endif
%global install_libexecdir %{install_prefix}/libexec
%global install_sharedir %{install_prefix}/share
%global install_docdir %{install_sharedir}/doc

%global clang_srcdir clang-%{clang_version}.src
%global clang_tools_srcdir clang-tools-extra-%{clang_version}.src
%global max_link_jobs %{_smp_build_ncpus}

# Disable LTO as this causes crash if gcc lto enabled.
%define _lto_cflags %{nil}

Name:		%{pkg_name}
Version:	%{clang_version}
Release:	3
Summary:	A C language family front-end for LLVM

License:	NCSA
URL:		http://llvm.org
Source0:	https://github.com/llvm/llvm-project/releases/download/llvmorg-%{clang_version}/%{clang_srcdir}.tar.xz
Source1:	https://github.com/llvm/llvm-project/releases/download/llvmorg-%{clang_version}/%{clang_tools_srcdir}.tar.xz

Patch0:     fedora-PATCH-clang-Reorganize-gtest-integration.patch
Patch1:     fedora-PATCH-clang-Don-t-install-static-libraries.patch

Patch201:   fedora-clang-tools-extra-Make-test-dependency-on-LLVMHello-.patch

BuildRequires:	gcc
BuildRequires:	gcc-c++
BuildRequires:	cmake
BuildRequires:	libatomic

%if %{with sys_llvm}
BuildRequires:	llvm-devel = %{version}
BuildRequires:	llvm-static = %{version}
BuildRequires:	llvm-test = %{version}
BuildRequires:	llvm-googletest = %{version}
%else
BuildRequires:	llvm%{maj_ver}-devel = %{version}
BuildRequires:	llvm%{maj_ver}-static = %{version}
BuildRequires:	llvm%{maj_ver}-test = %{version}
BuildRequires:	llvm%{maj_ver}-googletest = %{version}
%endif

BuildRequires:	libxml2-devel
BuildRequires:	multilib-rpm-config
BuildRequires:	ninja-build
BuildRequires:	ncurses-devel
BuildRequires:	perl-generators
BuildRequires:	python3-lit >= %{version}
BuildRequires:	python3-sphinx
BuildRequires:	python3-recommonmark
BuildRequires:	python3-devel

BuildRequires: perl(Digest::MD5)
BuildRequires: perl(File::Copy)
BuildRequires: perl(File::Find)
BuildRequires: perl(File::Path)
BuildRequires: perl(File::Temp)
BuildRequires: perl(FindBin)
BuildRequires: perl(Hash::Util)
BuildRequires: perl(lib)
BuildRequires: perl(Term::ANSIColor)
BuildRequires: perl(Text::ParseWords)
BuildRequires: perl(Sys::Hostname)

Requires:	%{name}-libs%{?_isa} = %{version}-%{release}

Requires:	libstdc++-devel
Requires:	gcc-c++

Provides:	clang(major) = %{maj_ver}

Conflicts:	compiler-rt < 11.0.0

%description
clang: noun
    1. A loud, resonant, metallic sound.
    2. The strident call of a crane or goose.
    3. C-language family front-end toolkit.

The goal of the Clang project is to create a new C, C++, Objective C
and Objective C++ front-end for the LLVM compiler. Its tools are built
as libraries and designed to be loosely-coupled and extensible.

Install compiler-rt if you want the Blocks C language extension or to
enable sanitization and profiling options when building, and
libomp-devel to enable -fopenmp.

%package libs
Summary: Runtime library for clang
Requires: %{name}-resource-filesystem%{?_isa} = %{version}
Recommends: compiler-rt%{?_isa} = %{version}
Recommends: libatomic%{?_isa}
Recommends: libomp-devel%{_isa} = %{version}
Recommends: libomp%{_isa} = %{version}

%description libs
Runtime library for clang.

%package devel
Summary: Development header files for clang
Requires: %{name}-libs = %{version}-%{release}

%description devel
Development header files for clang.

%package resource-filesystem
Summary: Filesystem package that owns the clang resource directory
Provides: %{name}-resource-filesystem(major) = %{maj_ver}

%description resource-filesystem
This package owns the clang resouce directory: $libdir/clang/$version/


%package analyzer
Summary:	A source code analysis framework
License:	NCSA and MIT
BuildArch:	noarch
Requires:	%{name} = %{version}-%{release}

%description analyzer
The Clang Static Analyzer consists of both a source code analysis
framework and a standalone tool that finds bugs in C and Objective-C
programs. The standalone tool is invoked from the command-line, and is
intended to run in tandem with a build of a project or code base.

%package tools-extra
Summary:	Extra tools for clang
Requires:	%{name}-libs%{?_isa} = %{version}-%{release}
Requires:	emacs-filesystem

%description tools-extra
A set of extra tools built using Clang's tooling API.

%package -n git-clang-format
Summary:	Integration of clang-format for git
Requires:	%{name}-tools-extra = %{version}-%{release}
Requires:	git
Requires:	python3

%description -n git-clang-format
clang-format integration for git.

%prep
%setup -T -q -b 1 -n %{clang_tools_srcdir}
%autopatch -m200 -p2

# failing test case
rm test/clang-tidy/checkers/altera/struct-pack-align.cpp

pathfix.py -i %{__python3} -pn \
	clang-tidy/tool/ \
	clang-include-fixer/find-all-symbols/tool/run-find-all-symbols.py

%setup -q -n %{clang_srcdir}
%autopatch -M200 -p2

# failing test case
rm test/CodeGen/profile-filter.c
rm test/CodeGen/2007-06-18-SextAttrAggregate.c
rm test/Driver/XRay/xray-instrument-os.c
rm test/Driver/XRay/xray-instrument-cpu.c
rm test/CodeGen/attr-noundef.cpp
rm test/CodeGen/indirect-noundef.cpp
rm test/Preprocessor/init.c

pathfix.py -i %{__python3} -pn \
	tools/clang-format/ \
	tools/clang-format/git-clang-format \
	utils/hmaptool/hmaptool \
	tools/scan-view/bin/scan-view \
	tools/scan-view/share/Reporter.py \
	tools/scan-view/share/startfile.py \
	tools/scan-build-py/bin/* \
	tools/scan-build-py/libexec/*

mv ../%{clang_tools_srcdir} tools/extra

%build
mkdir -p _build
cd _build
%cmake .. -G Ninja \
	-DCLANG_DEFAULT_PIE_ON_LINUX=ON \
	-DLLVM_PARALLEL_LINK_JOBS=%{max_link_jobs} \
	-DLLVM_LINK_LLVM_DYLIB:BOOL=ON \
	-DCMAKE_BUILD_TYPE=Release \
	-DPYTHON_EXECUTABLE=%{__python3} \
	-DCMAKE_SKIP_RPATH:BOOL=ON \
	-DCLANG_BUILD_TOOLS:BOOL=ON \
	-DCMAKE_INSTALL_PREFIX=%{install_prefix} \
	-DCLANG_INCLUDE_TESTS:BOOL=ON \
	-DLLVM_EXTERNAL_LIT=%{_bindir}/lit \
	-DLLVM_CONFIG:FILEPATH=%{install_bindir}/llvm-config \
	-DLLVM_TABLEGEN_EXE:FILEPATH=%{install_bindir}/llvm-tblgen \
	-DLLVM_MAIN_SRC_DIR=%{install_prefix}/src \
	-DLLVM_LIT_ARGS="-vv" \
	-DLLVM_BUILD_UTILS:BOOL=ON \
	-DCLANG_ENABLE_ARCMT:BOOL=ON \
	-DCLANG_ENABLE_STATIC_ANALYZER:BOOL=ON \
	-DCLANG_INCLUDE_DOCS:BOOL=ON \
	-DCLANG_PLUGIN_SUPPORT:BOOL=ON \
	-DENABLE_LINKER_BUILD_ID:BOOL=ON \
	-DLLVM_ENABLE_EH=ON \
	-DLLVM_ENABLE_RTTI=ON \
	-DLLVM_BUILD_DOCS=ON \
	-DLLVM_ENABLE_SPHINX=ON \
	-DCLANG_LINK_CLANG_DYLIB=ON \
	-DSPHINX_WARNINGS_AS_ERRORS=OFF \
	-DCLANG_BUILD_EXAMPLES:BOOL=OFF \
	-DBUILD_SHARED_LIBS=OFF \
	-DCLANG_REPOSITORY_STRING="%{?distro} %{version}-%{release}" \
%if 0%{?__isa_bits} == 64
	-DLLVM_LIBDIR_SUFFIX=64 \
%else
	-DLLVM_LIBDIR_SUFFIX= \
%endif
	-DCLANG_DEFAULT_UNWINDLIB=libgcc

%ninja_build

%install

%ninja_install -C _build
mkdir -p %{buildroot}/%{_bindir}

rm -vf %{buildroot}%{_datadir}/clang/clang-format-bbedit.applescript
rm -vf %{buildroot}%{_datadir}/clang/clang-format-sublime.py*

rm -vf %{buildroot}%{install_sharedir}/clang/clang-format-bbedit.applescript
rm -vf %{buildroot}%{install_sharedir}/clang/clang-format-sublime.py*

rm -Rvf %{buildroot}%{install_docdir}/Clang/clang/html
rm -Rvf %{buildroot}%{install_sharedir}/clang/clang-doc-default-stylesheet.css
rm -Rvf %{buildroot}%{install_sharedir}/clang/index.js
rm -vf %{buildroot}%{install_sharedir}/clang/bash-autocomplete.sh

mkdir -p %{buildroot}%{install_libdir}/clang/%{version}/{include,lib,share}/

%check
%if %{with check}

LD_LIBRARY_PATH=%{buildroot}/%{install_libdir}  %{__ninja} check-all -C ./_build/
%endif

%files
%license LICENSE.TXT
%{install_bindir}/clang
%{install_bindir}/clang++
%{install_bindir}/clang-%{maj_ver}
%{install_bindir}/clang-cl
%{install_bindir}/clang-cpp
%{install_prefix}/share/man/man1/*

%files libs
%{install_libdir}/*.so.*
%{install_libdir}/clang/%{version}/include/*

%files devel
%{install_libdir}/*.so
%{install_includedir}/clang/
%{install_includedir}/clang-c/
%{install_includedir}/clang-tidy/
%{install_libdir}/cmake/*


%files resource-filesystem
%dir %{install_libdir}/clang/%{version}/
%dir %{install_libdir}/clang/%{version}/include/
%dir %{install_libdir}/clang/%{version}/lib/
%dir %{install_libdir}/clang/%{version}/share/
%{install_libdir}/clang/%{version}/

%files analyzer
%{install_libexecdir}/ccc-analyzer
%{install_libexecdir}/c++-analyzer
%{install_libexecdir}/analyze-c++
%{install_libexecdir}/analyze-cc
%{install_libexecdir}/intercept-c++
%{install_libexecdir}/intercept-cc
%{install_bindir}/scan-view
%{install_bindir}/scan-build
%{install_bindir}/analyze-build
%{install_bindir}/intercept-build
%{install_bindir}/scan-build-py
%{install_prefix}/share/man/man1/*
%{install_prefix}/lib/libear
%{install_prefix}/lib/libscanbuild
%{install_sharedir}/scan-view
%{install_sharedir}/scan-build


%files tools-extra
%{install_bindir}/c-index-test
%{install_bindir}/clang-apply-replacements
%{install_bindir}/clang-change-namespace
%{install_bindir}/clang-check
%{install_bindir}/clang-doc
%{install_bindir}/clang-extdef-mapping
%{install_bindir}/clang-format
%{install_bindir}/clang-include-fixer
%{install_bindir}/clang-move
%{install_bindir}/clang-offload-bundler
%{install_bindir}/clang-offload-packager
%{install_bindir}/clang-offload-wrapper
%{install_bindir}/clang-linker-wrapper
%{install_bindir}/clang-nvlink-wrapper
%{install_bindir}/clang-pseudo
%{install_bindir}/clang-query
%{install_bindir}/clang-refactor
%{install_bindir}/clang-rename
%{install_bindir}/clang-reorder-fields
%{install_bindir}/clang-repl
%{install_bindir}/clang-scan-deps
%{install_bindir}/clang-tidy
%{install_bindir}/clangd
%{install_bindir}/diagtool
%{install_bindir}/hmaptool
%{install_bindir}/pp-trace
%{install_bindir}/find-all-symbols
%{install_bindir}/modularize
%{install_bindir}/run-clang-tidy
%{install_sharedir}/clang/clang-format.el
%{install_sharedir}/clang/clang-rename.el
%{install_sharedir}/clang/clang-include-fixer.el
%{install_sharedir}/clang/clang-format.py
%{install_sharedir}/clang/clang-format-diff.py
%{install_sharedir}/clang/clang-include-fixer.py
%{install_sharedir}/clang/clang-tidy-diff.py
%{install_sharedir}/clang/run-find-all-symbols.py
%{install_sharedir}/clang/clang-rename.py

%files -n git-clang-format
%{install_bindir}/git-clang-format

%changelog
* Sat Jul 08 2023 cf-zhao <zhaochuanfeng@huawei.com> -15.0.7-3
- Make this spec file support both system-version and multi-version.

* Wed Jun 7 2023 Chenxi Mao <chenxi.mao@suse.com> - 15.0.7-2
- Disable LTO as this causes crash if gcc lto enabled.
- Disbale unit tests, there are 3 test failed.

* Mon Feb 20 2023 Chenxi Mao <chenxi.mao@suse.com> - 15.0.7-1
- Upgrade to 15.0.7.

* Thu Feb 9 2023 Chenxi Mao <chenxi.mao@suse.com> - 15.0.6-2
- Enable clang unit tests.
- Leverage macro define instead of hardcode version number.
- Remove duplicated character.

* Mon Jan 2 2023 Chenxi Mao <chenxi.mao@suse.com> - 15.0.6-1
- Package init
