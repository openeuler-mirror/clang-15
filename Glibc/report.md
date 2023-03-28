# 基于 clang + llvm 编译构建 glibc 问题调研

## 背景描述

LLVM 编译器目前已经非常成熟并在很多场景下使用，glibc 是 GNU 发布的 libc 库，即 c 运行库。glibc 是 linux 系统中最底层的 api ，几乎其它任何运行库都会依赖于 glibc 。目前使用 LLVM 编译器编译 glibc 还存在不少问题，业界也对这个问题比较关心，本篇文章主要对使用 clang 编译 glibc 会遇到的问题进行一个总结以及介绍业界目前使用 clang 编译 glibc 的最新进展。

## Clang 编译 glibc 过程与问题

### Clang 编译 glibc 主要步骤

在下载完 glibc 之后，编译 glibc 主要有以下三个步骤：

- 使用 glibc/configure 生成 Makefile 。
- make 执行编译过程。
- make install 执行安装过程。

如果想要在 make 的步骤当中使用 clang 进行编译，可以使用软链接实现，但是这里有一点需要注意的是在使用 configure 生成 Makefile 的时候会进行一系列的软件版本的检查，因此在生成 Makefile 的阶段的时候还不能够对 gcc 进行软链接操作，在生成 Makefile 这一步必须要确保 gcc 命令是 GNU 编译器，才能够保证 Makefile 正确生成。

如果在第一步使用 gcc 命令最终真实使用的编译器是 clang 的话，configure 就会报下面的错误：

```bash
configure: error:
*** These critical programs are missing or too old: compiler
*** Check the INSTALL file for required versions.
```

### Make 编译出错跳过策略

在执行 make 进行编译的时候如果遇到编译错误就会退出，为了保证 make 命令能够继续执行下去发现更多的错误，可以分析 make 的编译日志，在执行一个编译命令的时候，make 就会在标准输出打印编译命令，因此在每次执行 make 命令的时候都可以将其标准输出保存到文件当中，然后对文件进行分析操作，从中可以提取到编译之后的目标，为了保证下次不在执行相同的命令，可以生成一个空的伪目标文件以保证下次跳过相同的命令，同时在执行 make 命令的时候可以将标准错误重定向到错误日志当中，以保证将编译错误留存下来。

### Clang 与 GCC 编译 glibc 的差异

在使用 clang 编译 glibc 的时候主要有以下四类问题，在后续会针对不同类别的问题举例：

- clang 比 gcc 更加严格，clang 一般不允许程序当中有模糊不清的程序代码片段，只有具有明确语意的代码才能够通过 clang 的编译。
- clang 当中不完全具备 glibc 当中所使用到的编译选项。
- clang 没有完全支持 glibc 当中所使用到的 gnu 编译器的扩展功能。
- clang 编译 glibc 时，对于头文件和宏处理的不够好。

#### Clang 比 gcc 更加严格

##### Inline assembly

一般来说，Clang 与 GCC 内联程序集扩展高度兼容，允许与 GCC 内联汇编相同的一组约束、修饰符和操作数。在使用 integrated assembler 的目标文件（如大多数 X86 目标文件）上，内联汇编器是通过 integrated assembler 运行的，而不是通过系统汇编器运行的（最常见的是系统汇编器 "gas" ， 即 GNU assembler）。LLVM集成汇编器与 GAS 极为兼容，但在一些小地方它更为严格，特别是有的地方 GAS 的做法是错误的，GAS 极有可能会编译出一些不安全的程序。


比如下面的程序

```c
asm("add %al, (%rax)"); // ✅ both in gcc and clang
asm("addw $4, (%rax)"); // ✅ both in gcc and clang
asm("add $4, (%rax)");  // ✅ in gcc but ❌ in clang
```

Clang 和 GAS 都能够成功编译第一条语句，因为第一条指令使用 8 位 %al 寄存器作为操作数，所以很明显它是 8 位加法。第二条指令也可以同时在 GAS 和 clang 当中通过，因为 w 后缀表示它是 16 位加法。GAS 能够编译最后一条指令，即使没有指定指令大小的内容（汇编器随机选择 32 位加法）。因为它是不明确的，第三条语句的汇编指令只能够说明将立即数 4 加到 rax 寄存器指向的地址当中去，但是并没有说明目的数的位数，而不同的位数造成的实际结果是不一样的，在 clang 当中不允许这样的行为，这种行为很可能会导致程序当中的错误。 因此如果想第三条指令编译成功就必须加上对应的目的数的位数，比如下面的四条语句能够在 clang 当中编译成功。

```c
asm("addb $4, (%rax);");
asm("addw $4, (%rax);");
asm("addl $4, (%rax);");
asm("addq $4, (%rax);");
```

因此如果想要程序在 clang 和 gcc 当中都能够成功进行编译的话最好在汇编指令上加上操作数据的位数，让程序的语意变得更加清晰，以同时适应 clang 和 gcc 。

##### 左值类型强制转换

旧版本的 GCC 允许将赋值的左侧映射为不同的类型。但是 clang 在类似代码上产生错误。

```c
(int*)addr = val; // error: assignment to cast is illegal, lvalue casts are not supported
```

解决这个问题只需要将类型转换放到右侧即可：

```c
addr = (float *)val;
```

#### Clang 不支持所有的在 glibc 当中使用的编译选项

在编译 glibc 当中的文件 rtld.c 和文件 dl-tunables.c 时使用到了编译选项 -fno-tree-loop-distribute-patterns，但是 clang 不支持这个编译选项。在使用 clang 编译 glibc 的时候产生了下面的错误：

```bash
clang-15: error: unknown argument: '-fno-tree-loop-distribute-patterns'
```

在 gcc 当中 tree-loop-distribute-patterns 是一种将循环赋值为 0 的数组，提出到循环外部从而可以调用 glibc 优化好的函数从而加快程序执行的效率。

```
DO I = 1, N
  A(I) = 0
  B(I) = A(I) + I
ENDDO
```

上面的代码将会被转换成下面的代码：

```
DO I = 1, N
   A(I) = 0
ENDDO
DO I = 1, N
   B(I) = A(I) + I
ENDDO
```

因为数组 A 是一个单独的循环，并且数组当中的数据全部都赋值等于 0 ，那么就可以调用 memset 函数将整个数组的是全部赋值成 0 。

在 clang 当中可以使用编译选项 -std=gun99，但是事实上 clang 并不完全实现了 -std=gun99 的所有语法，比如在 -std=gun99 当中的嵌套函数，使用 clang 对使用嵌套函数的代码进行编译，那么编译将不会通过。下面的代码当中使用到了 gnu99 的嵌套函数语法，如果使用 gcc 进行编译那么可以通过。

```c
#include <stdio.h>
int main() {
  int outer_variable = 10;
  int outer_function(int inner_parameter) {
  int inner_variable = 20;
  int inner_function(int innermost_parameter) {
    return outer_variable + inner_variable + innermost_parameter;
  }
    return inner_function(inner_parameter);
  }
  printf("Result: %d\n", outer_function(30));
  return 0; 
}
```

但是上面的代码如果使用 clang 进行编译的话将会产生以下错误：

```bash
demo.c:5:43: error: function definition is not allowed here
  int outer_function(int inner_parameter) {
                                          ^
demo.c:12:26: warning: implicit declaration of function 'outer_function' is
      invalid in C99 [-Wimplicit-function-declaration]
  printf("Result: %d\n", outer_function(30));
                         ^
1 warning and 1 error generated.
```

#### Clang 对 glibc 当中的头文件和宏的处理不够好

在使用 clang 对 glibc 进行编译的时候会产生大量的和头文件和宏定义相关的错误，大部分使用 clang 编译 glibc 程序的编译错误当中都含有头文件相关的错误。比如在使用 clang 编译 atoi.c 时，就产生了下面的错误：

```
In file included from atoi.c:18:
../include/stdlib.h:43:1: error: attribute declaration must precede definition [-Werror,-Wignored-attributes]
libc_hidden_proto (bsearch)
^
./../include/libc-symbols.h:620:44: note: expanded from macro 'libc_hidden_proto'
# define libc_hidden_proto(name, attrs...) hidden_proto (name, ##attrs)
                                           ^
./../include/libc-symbols.h:520:3: note: expanded from macro 'hidden_proto'
  __hidden_proto (name, , __GI_##name, ##attrs)
  ^
./../include/libc-symbols.h:526:47: note: expanded from macro '__hidden_proto'
  extern thread __typeof (name) name __asm__ (__hidden_asmname (#internal)) \
                                              ^
note: (skipping 1 expansions in backtrace; use -fmacro-backtrace-limit=0 to see all)
./../include/libc-symbols.h:532:43: note: expanded from macro '__hidden_asmname1'
#  define __hidden_asmname1(prefix, name) __hidden_asmname2(prefix, name)
                                          ^
./../include/libc-symbols.h:533:43: note: expanded from macro '__hidden_asmname2'
#  define __hidden_asmname2(prefix, name) #prefix name
                                          ^
<scratch space>:173:1: note: expanded from here
""
^
../bits/stdlib-bsearch.h:20:1: note: previous definition is here
bsearch (const void *__key, const void *__base, size_t __nmemb, size_t __size,
^
In file included from atoi.c:18:
../include/stdlib.h:43:1: error: attribute declaration must precede definition [-Werror,-Wignored-attributes]
libc_hidden_proto (bsearch)
^
./../include/libc-symbols.h:620:44: note: expanded from macro 'libc_hidden_proto'
# define libc_hidden_proto(name, attrs...) hidden_proto (name, ##attrs)
                                           ^
./../include/libc-symbols.h:520:3: note: expanded from macro 'hidden_proto'
  __hidden_proto (name, , __GI_##name, ##attrs)
  ^
./../include/libc-symbols.h:527:3: note: expanded from macro '__hidden_proto'
  __hidden_proto_hiddenattr (attrs);
  ^
./../include/libc-symbols.h:518:19: note: expanded from macro '__hidden_proto_hiddenattr'
  __attribute__ ((visibility ("hidden"), ##attrs))
                  ^
../bits/stdlib-bsearch.h:20:1: note: previous definition is here
bsearch (const void *__key, const void *__base, size_t __nmemb, size_t __size,
^
In file included from atoi.c:18:
../include/stdlib.h:234:20: error: cannot apply asm label to function after its first use
libc_hidden_proto (strtod)
~~~~~~~~~~~~~~~~~~~^~~~~~~
./../include/libc-symbols.h:620:58: note: expanded from macro 'libc_hidden_proto'
# define libc_hidden_proto(name, attrs...) hidden_proto (name, ##attrs)
                                           ~~~~~~~~~~~~~~^~~~~~~~~~~~~~
./../include/libc-symbols.h:520:19: note: expanded from macro 'hidden_proto'
  __hidden_proto (name, , __GI_##name, ##attrs)
  ~~~~~~~~~~~~~~~~^~~~~~~~~~~~~~~~~~~~~~~~~~~~~
./../include/libc-symbols.h:526:33: note: expanded from macro '__hidden_proto'
  extern thread __typeof (name) name __asm__ (__hidden_asmname (#internal)) \
                                ^             ~~~~~~~~~~~~~~~~~~~~~~~~~~~~
In file included from atoi.c:18:
../include/stdlib.h:238:20: error: cannot apply asm label to function after its first use
libc_hidden_proto (strtol)
~~~~~~~~~~~~~~~~~~~^~~~~~~
./../include/libc-symbols.h:620:58: note: expanded from macro 'libc_hidden_proto'
# define libc_hidden_proto(name, attrs...) hidden_proto (name, ##attrs)
                                           ~~~~~~~~~~~~~~^~~~~~~~~~~~~~
./../include/libc-symbols.h:520:19: note: expanded from macro 'hidden_proto'
  __hidden_proto (name, , __GI_##name, ##attrs)
  ~~~~~~~~~~~~~~~~^~~~~~~~~~~~~~~~~~~~~~~~~~~~~
./../include/libc-symbols.h:526:33: note: expanded from macro '__hidden_proto'
  extern thread __typeof (name) name __asm__ (__hidden_asmname (#internal)) \
                                ^             ~~~~~~~~~~~~~~~~~~~~~~~~~~~~
In file included from atoi.c:18:
../include/stdlib.h:239:20: error: cannot apply asm label to function after its first use
libc_hidden_proto (strtoll)
~~~~~~~~~~~~~~~~~~~^~~~~~~~
./../include/libc-symbols.h:620:58: note: expanded from macro 'libc_hidden_proto'
# define libc_hidden_proto(name, attrs...) hidden_proto (name, ##attrs)
                                           ~~~~~~~~~~~~~~^~~~~~~~~~~~~~
./../include/libc-symbols.h:520:19: note: expanded from macro 'hidden_proto'
  __hidden_proto (name, , __GI_##name, ##attrs)
  ~~~~~~~~~~~~~~~~^~~~~~~~~~~~~~~~~~~~~~~~~~~~~
./../include/libc-symbols.h:526:33: note: expanded from macro '__hidden_proto'
  extern thread __typeof (name) name __asm__ (__hidden_asmname (#internal)) \
                                ^             ~~~~~~~~~~~~~~~~~~~~~~~~~~~~
In file included from atoi.c:18:
../include/stdlib.h:243:1: error: attribute declaration must precede definition [-Werror,-Wignored-attributes]
libc_hidden_proto (atoi)
^
./../include/libc-symbols.h:620:44: note: expanded from macro 'libc_hidden_proto'
# define libc_hidden_proto(name, attrs...) hidden_proto (name, ##attrs)
                                           ^
./../include/libc-symbols.h:520:3: note: expanded from macro 'hidden_proto'
  __hidden_proto (name, , __GI_##name, ##attrs)
  ^
./../include/libc-symbols.h:526:47: note: expanded from macro '__hidden_proto'
  extern thread __typeof (name) name __asm__ (__hidden_asmname (#internal)) \
                                              ^
note: (skipping 1 expansions in backtrace; use -fmacro-backtrace-limit=0 to see all)
./../include/libc-symbols.h:532:43: note: expanded from macro '__hidden_asmname1'
#  define __hidden_asmname1(prefix, name) __hidden_asmname2(prefix, name)
                                          ^
./../include/libc-symbols.h:533:43: note: expanded from macro '__hidden_asmname2'
#  define __hidden_asmname2(prefix, name) #prefix name
                                          ^
<scratch space>:22:1: note: expanded from here
""
^
../stdlib/stdlib.h:362:8: note: previous definition is here
__NTH (atoi (const char *__nptr))
       ^
In file included from atoi.c:18:
../include/stdlib.h:243:1: error: attribute declaration must precede definition [-Werror,-Wignored-attributes]
libc_hidden_proto (atoi)
^
./../include/libc-symbols.h:620:44: note: expanded from macro 'libc_hidden_proto'
# define libc_hidden_proto(name, attrs...) hidden_proto (name, ##attrs)
                                           ^
./../include/libc-symbols.h:520:3: note: expanded from macro 'hidden_proto'
  __hidden_proto (name, , __GI_##name, ##attrs)
  ^
./../include/libc-symbols.h:527:3: note: expanded from macro '__hidden_proto'
  __hidden_proto_hiddenattr (attrs);
  ^
./../include/libc-symbols.h:518:19: note: expanded from macro '__hidden_proto_hiddenattr'
  __attribute__ ((visibility ("hidden"), ##attrs))
                  ^
../stdlib/stdlib.h:362:8: note: previous definition is here
__NTH (atoi (const char *__nptr))
       ^
7 errors generated.
```

在使用 clang 编译 glibc 的过程当中与上面的错误相类似问题还出现过很多次，都是因为引入头文件 libc-symbols.h 和在 glibc 的代码当中广泛使用 hidden_proto 和 libc_hidden_proto 。出现这个问题的主要原因是 clang 的编译模式 "one-function-at-a-time parsing and code generation "。 

比如在下面的代码当中使用 gcc 进行编译时可以通过的，但是使用 clang 进行编译就会产生错误：

```c
typedef unsigned long size_t;

extern void *memcpy(void *, const void *, size_t);

void *test_memcpy(void *dst, const void *src, size_t n) {
  return memcpy(dst, src, n);
}

extern void *memcpy(void *, const void *, size_t) asm("__GI_memcpy");
```

如果使用 clang 对上面的代码进行编译的话就会产生下面的错误。

```
demo.c:9:14: error: cannot apply asm label to function after its first use
extern void *memcpy(void *, const void *, size_t) asm("__GI_memcpy");
             ^                                        ~~~~~~~~~~~~~
1 error generated.
```

产生上面的编译错误的原因就是 clang "one-function-at-a-time parsing and code generation" 的编译策略。

上面的编译产生的错误 "cannot apply asm label to function after its first use" 在使用 clang 编译 glibc 的时候也遇到了，比如在编译 sysdeps/unix/sysv/linux/dl-getcwd.c 的时候就产生了如下错误：

```
In file included from ../sysdeps/unix/sysv/linux/dl-getcwd.c:1:
In file included from ../sysdeps/unix/sysv/linux/getcwd.c:45:
In file included from ../sysdeps/posix/getcwd.c:107:
../sysdeps/unix/sysv/linux/not-cancel.h:94:15: error: cannot apply asm label to function after its first use
hidden_proto (__close_nocancel)
~~~~~~~~~~~~~~^~~~~~~~~~~~~~~~~
./../include/libc-symbols.h:520:19: note: expanded from macro 'hidden_proto'
  __hidden_proto (name, , __GI_##name, ##attrs)
  ~~~~~~~~~~~~~~~~^~~~~~~~~~~~~~~~~~~~~~~~~~~~~
./../include/libc-symbols.h:526:33: note: expanded from macro '__hidden_proto'
  extern thread __typeof (name) name __asm__ (__hidden_asmname (#internal)) \
                                ^             ~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1 error generated.
```

## Clang 编译 glibc 错误列表

### 修改 glibc 源程序

#### No.1

下面的错误主要是由于 clang 的  one-function-at-a-time parsing and code generation  编译策略造成的，因为这个编译策略导致 clang 无法完全匹配 gcc 的行为，这个错误目前只能通过修改源程序解决问题。

```bash
../include/stdlib.h:43:1: error: attribute declaration must precede definition [-Werror,-Wignored-attributes]
libc_hidden_proto (bsearch)
^

gcc scandirat.c -c -std=gnu11 -fgnu89-inline  -g -O2 -Wall -Wwrite-strings -Wundef -Werror -fmerge-all-constants -frounding-math -fno-stack-protector -fno-common -Wstrict-prototypes -Wold-style-definition -fmath-errno    -fpie   -ftls-model=initial-exec      -I../include -I/root/workdir/build_2_36/dirent  -I/root/workdir/build_2_36  -I../sysdeps/unix/sysv/linux/x86_64/64  -I../sysdeps/unix/sysv/linux/x86_64  -I../sysdeps/unix/sysv/linux/x86/include -I../sysdeps/unix/sysv/linux/x86  -I../sysdeps/x86/nptl  -I../sysdeps/unix/sysv/linux/wordsize-64  -I../sysdeps/x86_64/nptl  -I../sysdeps/unix/sysv/linux/include -I../sysdeps/unix/sysv/linux  -I../sysdeps/nptl  -I../sysdeps/pthread  -I../sysdeps/gnu  -I../sysdeps/unix/inet  -I../sysdeps/unix/sysv  -I../sysdeps/unix/x86_64  -I../sysdeps/unix  -I../sysdeps/posix  -I../sysdeps/x86_64/64  -I../sysdeps/x86_64/fpu/multiarch  -I../sysdeps/x86_64/fpu  -I../sysdeps/x86/fpu  -I../sysdeps/x86_64/multiarch  -I../sysdeps/x86_64  -I../sysdeps/x86/include -I../sysdeps/x86  -I../sysdeps/ieee754/float128  -I../sysdeps/ieee754/ldbl-96/include -I../sysdeps/ieee754/ldbl-96  -I../sysdeps/ieee754/dbl-64  -I../sysdeps/ieee754/flt-32  -I../sysdeps/wordsize-64  -I../sysdeps/ieee754  -I../sysdeps/generic  -I.. -I../libio -I.  -D_LIBC_REENTRANT -include /root/workdir/build_2_36/libc-modules.h -DMODULE_NAME=libc -include ../include/libc-symbols.h  -DPIC     -DTOP_NAMESPACE=glibc -o /root/workdir/build_2_36/dirent/scandirat.o -MD -MP -MF /root/workdir/build_2_36/dirent/scandirat.o.dt -MT /root/workdir/build_2_36/dirent/scandirat.o
```

#### No.2

下面的错误也是由于 clang 的  one-function-at-a-time parsing and code generation  编译策略造成的。

```bash
../include/stdlib.h:234:20: error: cannot apply asm label to function after its first use
libc_hidden_proto (strtod)
~~~~~~~~~~~~~~~~~~~^~~~~~~

gcc pthread_join.c -c -std=gnu11 -fgnu89-inline  -g -O2 -Wall -Wwrite-strings -Wundef -Werror -fmerge-all-constants -frounding-math -fno-stack-protector -fno-common -Wstrict-prototypes -Wold-style-definition -fmath-errno    -fPIC -fexceptions -fasynchronous-unwind-tables  -ftls-model=initial-exec      -I../include -I/root/workdir/build_2_36/nptl  -I/root/workdir/build_2_36  -I../sysdeps/unix/sysv/linux/x86_64/64  -I../sysdeps/unix/sysv/linux/x86_64  -I../sysdeps/unix/sysv/linux/x86/include -I../sysdeps/unix/sysv/linux/x86  -I../sysdeps/x86/nptl  -I../sysdeps/unix/sysv/linux/wordsize-64  -I../sysdeps/x86_64/nptl  -I../sysdeps/unix/sysv/linux/include -I../sysdeps/unix/sysv/linux  -I../sysdeps/nptl  -I../sysdeps/pthread  -I../sysdeps/gnu  -I../sysdeps/unix/inet  -I../sysdeps/unix/sysv  -I../sysdeps/unix/x86_64  -I../sysdeps/unix  -I../sysdeps/posix  -I../sysdeps/x86_64/64  -I../sysdeps/x86_64/fpu/multiarch  -I../sysdeps/x86_64/fpu  -I../sysdeps/x86/fpu  -I../sysdeps/x86_64/multiarch  -I../sysdeps/x86_64  -I../sysdeps/x86/include -I../sysdeps/x86  -I../sysdeps/ieee754/float128  -I../sysdeps/ieee754/ldbl-96/include -I../sysdeps/ieee754/ldbl-96  -I../sysdeps/ieee754/dbl-64  -I../sysdeps/ieee754/flt-32  -I../sysdeps/wordsize-64  -I../sysdeps/ieee754  -I../sysdeps/generic  -I.. -I../libio -I.  -D_LIBC_REENTRANT -include /root/workdir/build_2_36/libc-modules.h -DMODULE_NAME=libc -include ../include/libc-symbols.h  -DPIC -DSHARED     -DTOP_NAMESPACE=glibc -o /root/workdir/build_2_36/nptl/pthread_join.os -MD -MP -MF /root/workdir/build_2_36/nptl/pthread_join.os.dt -MT /root/workdir/build_2_36/nptl/pthread_join.os
```

#### No.3

这个错误就是变量没有初始化的问题，只需要修改对应的源程序即可，比较容易解，或者去掉编译选项 Werror 或者 Wuninitialized 即可。

```bash
./allocatestack.c:188:30: error: variable 'frame' is uninitialized when used here [-Werror,-Wuninitialized]
  uintptr_t sp = (uintptr_t) CURRENT_STACK_FRAME;
                             ^~~~~~~~~~~~~~~~~~~
```

#### No.4

```bash
../sysdeps/unix/sysv/linux/clock_nanosleep.c:37:16: error: shifting a negative signed value is undefined [-Werror,-Wshift-negative-value]
    clock_id = MAKE_PROCESS_CPUCLOCK (0, CPUCLOCK_SCHED);
               ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
```

#### No.5

```bash
../stdlib/fpioconst.h:59:5: error: macro expansion producing 'defined' has undefined behavior [-Werror,-Wexpansion-to-defined]
#if FPIOCONST_HAVE_EXTENDED_RANGE
    ^

gcc wcstof_l.c -c -std=gnu11 -fgnu89-inline  -g -O2 -Wall -Wwrite-strings -Wundef -Werror -fmerge-all-constants -frounding-math -fno-stack-protector -fno-common -Wstrict-prototypes -Wold-style-definition -fmath-errno    -fpie -I../include  -ftls-model=initial-exec      -I../include -I/root/workdir/build_2_36/wcsmbs  -I/root/workdir/build_2_36  -I../sysdeps/unix/sysv/linux/x86_64/64  -I../sysdeps/unix/sysv/linux/x86_64  -I../sysdeps/unix/sysv/linux/x86/include -I../sysdeps/unix/sysv/linux/x86  -I../sysdeps/x86/nptl  -I../sysdeps/unix/sysv/linux/wordsize-64  -I../sysdeps/x86_64/nptl  -I../sysdeps/unix/sysv/linux/include -I../sysdeps/unix/sysv/linux  -I../sysdeps/nptl  -I../sysdeps/pthread  -I../sysdeps/gnu  -I../sysdeps/unix/inet  -I../sysdeps/unix/sysv  -I../sysdeps/unix/x86_64  -I../sysdeps/unix  -I../sysdeps/posix  -I../sysdeps/x86_64/64  -I../sysdeps/x86_64/fpu/multiarch  -I../sysdeps/x86_64/fpu  -I../sysdeps/x86/fpu  -I../sysdeps/x86_64/multiarch  -I../sysdeps/x86_64  -I../sysdeps/x86/include -I../sysdeps/x86  -I../sysdeps/ieee754/float128  -I../sysdeps/ieee754/ldbl-96/include -I../sysdeps/ieee754/ldbl-96  -I../sysdeps/ieee754/dbl-64  -I../sysdeps/ieee754/flt-32  -I../sysdeps/wordsize-64  -I../sysdeps/ieee754  -I../sysdeps/generic  -I.. -I../libio -I.  -D_LIBC_REENTRANT -include /root/workdir/build_2_36/libc-modules.h -DMODULE_NAME=libc -include ../include/libc-symbols.h  -DPIC     -DTOP_NAMESPACE=glibc -D_IO_MTSAFE_IO -o /root/workdir/build_2_36/wcsmbs/wcstof_l.o -MD -MP -MF /root/workdir/build_2_36/wcsmbs/wcstof_l.o.dt -MT /root/workdir/build_2_36/wcsmbs/wcstof_l.o
```

#### No.6

```bash
../sysdeps/wordsize-64/strtoul.c:13:22: error: incompatible redeclaration of library function 'strtoull' [-Werror,-Wincompatible-library-redeclaration]
weak_alias (strtoul, strtoull)
                     ^
```

#### No.7

这个错误比较简单，将这行语句删除，或者去掉对应的编译选项即可。

```bash
/root/workdir/build_2_36/intl/plural.c:1125:9: error: variable '__gettextnerrs' set but not used [-Werror,-Wunused-but-set-variable]
    int yynerrs;
        ^
```

#### No.8

这个错误主要是由于数据的类型不匹配，去掉对应的编译选项即可。

```bash
pthread_join_common.c:32:3: error: incompatible pointer types passing 'struct pthread **' to parameter of type 'void **' [-Werror,-Wincompatible-pointer-types]
  atomic_compare_exchange_weak_acquire (&arg, &self, NULL);
  ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
```

#### No.9

去掉对应的编译选项 -Werror 或者 -Wtautological-constant-out-of-range-compare即可。

```bash
vfprintf-internal.c:1383:13: error: result of comparison of constant 255 with expression of type 'char' is always true [-Werror,-Wtautological-constant-out-of-range-compare]
          if (spec <= UCHAR_MAX
              ~~~~ ^  ~~~~~~~~~
```

#### No.10

```bash
../sysdeps/unix/sysv/linux/mmap_internal.h:31:21: error: right side of operator converted from negative value to unsigned: -1 to 18446744073709551615 [-Werror]
#if MMAP2_PAGE_UNIT == -1
    ~~~~~~~~~~~~~~~ ^  ~~

gcc ../sysdeps/unix/sysv/linux/mmap64.c -c -std=gnu11 -fgnu89-inline  -g -O2 -Wall -Wwrite-strings -Wundef -Werror -fmerge-all-constants -frounding-math -fno-stack-protector -fno-common -Wstrict-prototypes -Wold-style-definition -fmath-errno    -fpie  -fno-stack-protector -DSTACK_PROTECTOR_LEVEL=0 -ftls-model=initial-exec      -I../include -I/root/workdir/build_2_36/misc  -I/root/workdir/build_2_36  -I../sysdeps/unix/sysv/linux/x86_64/64  -I../sysdeps/unix/sysv/linux/x86_64  -I../sysdeps/unix/sysv/linux/x86/include -I../sysdeps/unix/sysv/linux/x86  -I../sysdeps/x86/nptl  -I../sysdeps/unix/sysv/linux/wordsize-64  -I../sysdeps/x86_64/nptl  -I../sysdeps/unix/sysv/linux/include -I../sysdeps/unix/sysv/linux  -I../sysdeps/nptl  -I../sysdeps/pthread  -I../sysdeps/gnu  -I../sysdeps/unix/inet  -I../sysdeps/unix/sysv  -I../sysdeps/unix/x86_64  -I../sysdeps/unix  -I../sysdeps/posix  -I../sysdeps/x86_64/64  -I../sysdeps/x86_64/fpu/multiarch  -I../sysdeps/x86_64/fpu  -I../sysdeps/x86/fpu  -I../sysdeps/x86_64/multiarch  -I../sysdeps/x86_64  -I../sysdeps/x86/include -I../sysdeps/x86  -I../sysdeps/ieee754/float128  -I../sysdeps/ieee754/ldbl-96/include -I../sysdeps/ieee754/ldbl-96  -I../sysdeps/ieee754/dbl-64  -I../sysdeps/ieee754/flt-32  -I../sysdeps/wordsize-64  -I../sysdeps/ieee754  -I../sysdeps/generic  -I.. -I../libio -I.  -D_LIBC_REENTRANT -include /root/workdir/build_2_36/libc-modules.h -DMODULE_NAME=libc -include ../include/libc-symbols.h  -DPIC     -DTOP_NAMESPACE=glibc -o /root/workdir/build_2_36/misc/mmap64.o -MD -MP -MF /root/workdir/build_2_36/misc/mmap64.o.dt -MT /root/workdir/build_2_36/misc/mmap64.o
```

#### No.11

```bash
../sysdeps/wordsize-64/strtol.c:13:21: error: incompatible redeclaration of library function 'strtoll' [-Werror,-Wincompatible-library-redeclaration]
weak_alias (strtol, strtoll)
                    ^
```

#### No.12

```bash
dl-profile.c:551:21: error: unsupported inline asm: input with type 'int64_t' (aka 'long') matching output with type 'typeof (*&fromidx)' (aka 'volatile unsigned int')
              newfromidx = catomic_exchange_and_add (&fromidx, 1) + 1;
                           ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
dl-profile.c:561:30: error: unsupported inline asm: input with type 'int64_t' (aka 'long') matching output with type 'typeof (*narcsp)' (aka 'volatile unsigned int')
              unsigned int newarc = catomic_exchange_and_add (narcsp, 1);
                                    ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
```

#### No.13

下方的代码主要是可能会存在未初始化的问题，对应的源程序如下所示：

```c
  struct r_debug_extended *r, **pp = NULL;

  if (ns == LM_ID_BASE)
    {
      r = &_r_debug_extended;
      /* Initialize r_version to 1.  */
      if (_r_debug_extended.base.r_version == 0)
	_r_debug_extended.base.r_version = 1;
    }
```

```bash
dl-debug.c:59:7: error: variable 'r' is used uninitialized whenever 'if' condition is false [-Werror,-Wsometimes-uninitialized]
  if (ns == LM_ID_BASE)
      ^~~~~~~~~~~~~~~~
```

同样的错误也出现在了其他地方：

```bash
../sysdeps/posix/getaddrinfo.c:1870:11: error: variable 'endp' is used uninitialized whenever '||' condition is true [-Werror,-Wsometimes-uninitialized]
      && (cp == NULL
          ^~~~~~~~~~
```

这个错误只需要修改对应的编译选项即可通过。

#### No.14

下面的代码也是去掉编译选项 -Werror 即可，在 [gcc](https://gcc.gnu.org/bugzilla/show_bug.cgi?id=62181) 中有关于它和 clang 在这个问题上的讨论。

```bash
nss_module.c:44:20: error: adding 'unsigned long' to a string does not append to the string [-Werror,-Wstring-plus-int]
        = LIBNSS_FILES_SO + sizeof("libnss_files.so") - 1;
          ~~~~~~~~~~~~~~~~^~~~~~~~~~~~~~~~~~~~~~~~~~~
syslog.c:181:7: error: adding 'int' to a string does not append to the string [-Werror,-Wstring-plus-int]
                    SYSLOG_HEADER (pri, timestamp, &msgoff, pid));
                    ^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
```

#### No.15

```bash
../sysdeps/x86_64/ffs.c:38:1: error: alias will always resolve to __GI___ffs even if weak definition of __GI_ffs is overridden [-Werror,-Wignored-attributes]
libc_hidden_builtin_def (ffs)
^
memmem.c:129:1: error: alias will always resolve to __GI___memmem even if weak definition of __GI_memmem is overridden [-Werror,-Wignored-attributes]
libc_hidden_weak (memmem)
^
lockf64.c:61:1: error: alias will always resolve to __lockf64 even if weak definition of lockf64 is overridden [-Werror,-Wignored-attributes]
weak_alias (lockf64, lockf)
^
confstr.c:293:1: error: alias will always resolve to __GI___confstr even if weak definition of __GI_confstr is overridden [-Werror,-Wignored-attributes]
libc_hidden_def (confstr)
^
```

#### No.16

在编译 glibc 的过程当中会使用 gcc 解析內联汇编的方式去得到一个常量宏对应的常量值（比如得到一些系统调用的调用号）。具体的是使用 glibc/scripts/glibcextract.py 当中的 compute_c_consts 函数实现的，在这个函数当中会创建一个子进程去调用 gcc -S 生成汇编内容，然后使用 grep 命令得到常量宏的值。但是在使用 clang 这样进行求解常量的时候会又一些问题。下面是一个具体的简化例子，主要是用与描述提到的问题所产生的错误：

```c
// demo.c
#include <linux/version.h>
#include <sys/syscall.h>
#include <bits/syscall.h>

int main() {
  asm ("@@@%0@@@" :: "i"((long int)(X)));
}
```

```
$gcc -S -DX=__NR_exit demo.c -o - | grep @@@
$        @@@$60@@@
```

使用上面的命令可以正确的得到 exit 的系统调用号 60，但是如果使用 clang 执行上面的命令就会报错：

```
$clang -S -DX=__NR_exit demo.c -o - | grep @@@
demo.c:6:8: error: unexpected token at start of statement
  asm ("@@@%0@@@" :: "i"((long int)(X)));
       ^
<inline asm>:1:3: note: instantiated into assembly here
        @@@$60@@@
         ^
1 error generated.
```

### 修改编译器

#### No.17

下面是 clang 的处理错误，下面的错误对应的源程序如下所示：

```c
if (__glibc_unlikely (GLRO(dl_debug_mask) & DL_DEBUG_FILES))
     _dl_debug_printf ("\
   dynamic: 0x%0*lx  base: 0x%0*lx   size: 0x%0*Zx\n\
     entry: 0x%0*lx  phdr: 0x%0*lx  phnum:   %*u\n\n",
                (int) sizeof (void *) * 2,
                (unsigned long int) l->l_ld,
                (int) sizeof (void *) * 2,
                (unsigned long int) l->l_addr,
                (int) sizeof (void *) * 2, maplength,
                (int) sizeof (void *) * 2,
                (unsigned long int) l->l_entry,
                (int) sizeof (void *) * 2,
                (unsigned long int) l->l_phdr,
                (int) sizeof (void *) * 2, l->l_phnum);
```

由于 clang 在处理这个源程序时没有正确处理第一个参数字符串，而导致出现了错误。

```bash
dl-load.c:1409:48: error: invalid conversion specifier 'Z' [-Werror,-Wformat-invalid-specifier]
  dynamic: 0x%0*lx  base: 0x%0*lx   size: 0x%0*Zx\n\
                                            ~~~^
dl-load.c:1410:17: error: field width should have type 'int', but argument has type 'size_t' (aka 'unsigned long') [-Werror,-Wformat]
    entry: 0x%0*lx  phdr: 0x%0*lx  phnum:   %*u\n\n",
             ~~~^~
```

#### No.18

```bash
./net-internal.h:109:1: error: unknown warning group '-Wmaybe-uninitialized', ignored [-Werror,-Wunknown-warning-option]
DIAG_IGNORE_NEEDS_COMMENT (9, "-Wmaybe-uninitialized");
^

gcc deadline.c -c -std=gnu11 -fgnu89-inline  -g -O2 -Wall -Wwrite-strings -Wundef -Werror -fmerge-all-constants -frounding-math -fno-stack-protector -fno-common -Wstrict-prototypes -Wold-style-definition -fmath-errno    -fpie   -ftls-model=initial-exec      -I../include -I/root/workdir/build_2_36/inet  -I/root/workdir/build_2_36  -I../sysdeps/unix/sysv/linux/x86_64/64  -I../sysdeps/unix/sysv/linux/x86_64  -I../sysdeps/unix/sysv/linux/x86/include -I../sysdeps/unix/sysv/linux/x86  -I../sysdeps/x86/nptl  -I../sysdeps/unix/sysv/linux/wordsize-64  -I../sysdeps/x86_64/nptl  -I../sysdeps/unix/sysv/linux/include -I../sysdeps/unix/sysv/linux  -I../sysdeps/nptl  -I../sysdeps/pthread  -I../sysdeps/gnu  -I../sysdeps/unix/inet  -I../sysdeps/unix/sysv  -I../sysdeps/unix/x86_64  -I../sysdeps/unix  -I../sysdeps/posix  -I../sysdeps/x86_64/64  -I../sysdeps/x86_64/fpu/multiarch  -I../sysdeps/x86_64/fpu  -I../sysdeps/x86/fpu  -I../sysdeps/x86_64/multiarch  -I../sysdeps/x86_64  -I../sysdeps/x86/include -I../sysdeps/x86  -I../sysdeps/ieee754/float128  -I../sysdeps/ieee754/ldbl-96/include -I../sysdeps/ieee754/ldbl-96  -I../sysdeps/ieee754/dbl-64  -I../sysdeps/ieee754/flt-32  -I../sysdeps/wordsize-64  -I../sysdeps/ieee754  -I../sysdeps/generic  -I.. -I../libio -I.  -D_LIBC_REENTRANT -include /root/workdir/build_2_36/libc-modules.h -DMODULE_NAME=libc -include ../include/libc-symbols.h  -DPIC     -DTOP_NAMESPACE=glibc -o /root/workdir/build_2_36/inet/deadline.o -MD -MP -MF /root/workdir/build_2_36/inet/deadline.o.dt -MT /root/workdir/build_2_36/inet/deadline.o
```

#### No.19

这个错误是因为 clang 目前并不支持 _Float128 类型，目前已经开始有 [patch](https://reviews.llvm.org/D111382) 去解决这个问题了

```bash
../stdlib/strtod_l.c:309:4: error: unknown type name '_Float128'
          math_force_eval (force_underflow);
          ^
../sysdeps/ieee754/float128/mpn2float128.c:48:15: error: use of undeclared identifier 'FLT128_MANT_DIG'
                                             << (FLT128_MANT_DIG - 96)) - 1);
                                                 ^
../sysdeps/ieee754/float128/float128_private.h:419:12: error: expected ';' after expression
  _Float128 x1 = x * C;
           ^
../sysdeps/ieee754/float128/float128_private.h:419:3: error: use of undeclared identifier '_Float128'
  _Float128 x1 = x * C;
  ^
../sysdeps/ieee754/float128/float128_private.h:419:13: error: use of undeclared identifier 'x1'
  _Float128 x1 = x * C;
            ^
../sysdeps/generic/math-type-macros.h:131:5: error: 'FLT128_MANT_DIG' is not defined, evaluates to 0 [-Werror,-Wundef]
#if M_MANT_DIG != 106
    ^
 ../stdlib/strtod_nan_main.c:43:9: error: use of undeclared identifier 'retval'
  FLOAT retval = NAN;
        ^
```

#### No.20

```bash
../sysdeps/x86_64/multiarch/strstr.c:64:1: error: unknown attribute '__optimize__' ignored [-Werror,-Wunknown-attributes]
libc_ifunc_redirected (__redirect_strstr, __libc_strstr, IFUNC_SELECTOR ());
^~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
```

#### No.21

下面的错误和编译选项 -Wimplicit-function-declaration 有关，在 [llvm](https://reviews.llvm.org/D122983) 当中有关于它的讨论。

```bash
./s_ldexp_template.c:24:10: error: call to undeclared function '__scalbnf128'; ISO C99 and later do not support implicit function declarations [-Werror,-Wimplicit-function-declaration]
        value = M_SCALBN(value,exp);
                ^
```

#### No.22

在编译 glibc 当中的文件 rtld.c 和文件 dl-tunables.c 时使用到了编译选项 -fno-tree-loop-distribute-patterns，但是 clang 不支持这个编译选项。在使用 clang 编译 glibc 的时候产生了下面的错误：

```bash
clang-15: error: unknown argument: '-fno-tree-loop-distribute-patterns'
```

#### No.23

clang 并没有完全实现 -std=gnu99 的语法，比如嵌套函数，目前在 glibc 当中已经开始有 [patch](https://sourceware.org/git/?p=glibc.git;a=commit;h=fdcd177fd36c60ddc9cbc6013831413dbd83c3f9) 去解决这个问题了，这个 patch 主要是将 glibc/posix/regcomp.c 文件当中的嵌套函数提出来，并且使用 static always_inline 函数代替。

#### No.24

在 glibc-alpha 当中已经开始有 patch 解决这个问题了，解决方法就是不使用这个选项 [[PATCH 06/11] Disable use of -fsignaling-nans if compiler does not support it](https://sourceware.org/pipermail/libc-alpha/2022-October/143063.html) 。

```
optimization flag '-fsignaling-nans' is not supported [-Werror,-Wignored-optimization-argument]
```

#### No.25

同样的，在 glibc-alpha 当中已经开始有 patch 解决这个问题了，解决方法就是不使用这个选项 ，[[PATCH v2 3/4] stdlib: Remove if inline asm context casts if compiler does not support it](https://sourceware.org/pipermail/libc-alpha/2022-November/143151.html) 。

```
../stdlib/strtod_l.c:1606:25: error: invalid use of a cast in a inline asm context requiring an lvalue: remove the cast or build with -fheinous-gnu-extensions
                      add_ssaaaa (n1, n0, r - d0, 0, 0, d0);
                      ~~~~~~~~~~~~~~~~^~~~~~~~~~~~~~~~~~~~~
```

## Clang 编译 glibc 问题总结

在本文当中一共提到了使用 clang 编译 glibc 当中的 **25**个 clang 编译 glibc 的错误，主要可以分为 **修改编译器 **和 **修改 glibc 源程序** 两大类。其中的部分错误可以通过去掉编译选项 -Werror 解决，有些目前已经开始有 patch 进行相关的修复操作了。但是需要注意的是在 clang 当中的有些 warning 也会导致无法继续进行编译，比如很多的头文件警告就会导致无法进行进行编译操作，因此这些问题解决之后可能还会存在一些问题，但是问题应该都比较少了，因为 clang 编译 glibc 当中的很多文件都是编译成功的。在使用 clang 编译 glibc 产生次数较多的 error 如下表所示：

|Error|出现次数|
|---|---|
|attribute declaration must precede definition [-Werror,-Wignored-attributes]|19612|
|cannot apply asm label to function after its first use|6778|
|unknown type name '_Float128'|204|
|remove the cast or build with -fheinous-gnu-extensions|156|
|unknown attribute '\_\_optimize\_\_' ignored [-Werror,-Wunknown-attributes]|89|
|use of undeclared identifier '_Float128'|43|
|macro expansion producing 'defined' has undefined behavior [-Werror,-Wexpansion-to-defined]|30|
|unknown warning group '-Wmaybe-uninitialized', ignored [-Werror,-Wunknown-warning-option]|18|
|optimization flag '-fsignaling-nans' is not supported [-Werror,-Wignored-optimization-argument]|8|
|shifting a negative signed value is undefined [-Werror,-Wshift-negative-value]|6|
|'FLT128_MANT_DIG' is not defined, evaluates to 0 [-Werror,-Wundef]|6|


## Clang 编译 glibc 最新进展

Libc-alpha 是一个讨论 glibc 发展的项目，在最近几年当中关于使用 clang 编译 glibc 的讨论越来越多，同时在项目 Libc-alpha 当中关于使用 clang 编译 glibc 的 patch 也慢慢多了起来，下面的图表数据是对近些年来在 Libc-alpha 当中与 clang 有关的 patch 的数据统计，在本小节末给出了项目 Libc-alpha 当中含有 clang 关键字的 patch 。

不同的作者在 2022 年往 Libc-alpha 中提交的含有 clang 关键字的 patch 的数量：

![author](figs/author.svg)

下图是 2022 年来不同的月份 Libc-alpha 中与 clang 有关的 patch 数量：

![date](figs/date.svg)

下图是在 Libc-alpha 中近几年与 clang 相关的 patch 的数量：

![year](figs/year.svg)

从上面的图表可以知道，近几年与 clang 相关的补丁也越来越多了，根据上面的图表数据可以知道 **Alejandro Zanella** 、**Fangrui Song** 和 **Noah Goldstein** 等作者在给 glibc-alpha 提交 clang 相关的补丁方面比较活跃。**Alejandro Zanella**和 **Fangrui Song** 也一直在跟踪 clang 编译 glibc ，并且也不断的在给 glibc-alpha 提交补丁。

虽然在 glibc-alpha 上开始有 clang 编译 glibc 的补丁了，但是想要完全支持 clang 编译 glibc 仍然还有许多的工作需要完成，在使用 clang 编译 glibc 时会有大量的细小的问题，要想最终实现 clang 正确编译 glibc ，这需要工程师长时间的修复工作。

2022 年 10 月 **Adhemerval Zanella** adhemerval.zanella@linaro.org 在 glibc-alpha 提交了 clang 编译 glibc 的初始修复 patch ，在这个 patch 当中修复了在使用 clang 编译 glibc 的时候一些配置错误并且，修复 pthread_create.c 使之能够使用 clang 进行编译。其实之前就有一些修复 clang 编译 glibc 了，比如说  [[PATCH] x86: Remove .tfloat usage](https://sourceware.org/pipermail/libc-alpha/2022-September/142237.html) 。但是这些修复也只是修复 clang 编译 glibc 的部分问题，但是要想使用 clang 正确编译 glibc ，后需还需要更多的工作需要完成，目前整个工作离完全使用 clang 编译 glibc 还差很远，这一点在 [[patch]Initial fixes for clang build support](https://sourceware.org/pipermail/libc-alpha/2022-October/143036.html) 当中也提到了。

下面是 Libc-alpha 2022 年所有提到 clang 的 patch 列表：

| Date           | Commit Message                                               | Author                           |
| -------------- | ------------------------------------------------------------ | -------------------------------- |
| 2022-December  | [[PATCH 1/1] string: Add stpecpy(3)](https://sourceware.org/pipermail/libc-alpha/2022-December/144311.html) | Alejandro Colomar                |
| 2022-December  | [[PATCH 1/1] string: Add stpecpy(3)](https://sourceware.org/pipermail/libc-alpha/2022-December/144308.html) | Alejandro Colomar                |
| 2022-December  | [[PATCH 1/1] string: Add stpecpy(3)](https://sourceware.org/pipermail/libc-alpha/2022-December/144310.html) | Alejandro Colomar                |
| 2022-December  | [Add restrict annotations to all functions that require it](https://sourceware.org/pipermail/libc-alpha/2022-December/143708.html) | Alejandro Colomar                |
| 2022-November  | [[PATCH 01/11] stdlib/longlong.h: Remove incorrect lvalue to rvalue conversion from asm output constraints](https://sourceware.org/pipermail/libc-alpha/2022-November/143127.html) | Adhemerval Zanella Netto         |
| 2022-November  | [[PATCH v2 0/4] Initial fixes for clang build support](https://sourceware.org/pipermail/libc-alpha/2022-November/143148.html) | Adhemerval Zanella               |
| 2022-November  | [[PATCH v2 1/4] Disable __USE_EXTERN_INLINES for clang](https://sourceware.org/pipermail/libc-alpha/2022-November/143149.html) | Adhemerval Zanella               |
| 2022-November  | [[PATCH v2 2/4] Rewrite find_cxx_header config configure.ac](https://sourceware.org/pipermail/libc-alpha/2022-November/143150.html) | Adhemerval Zanella               |
| 2022-November  | [[PATCH v2 2/4] Rewrite find_cxx_header config configure.ac](https://sourceware.org/pipermail/libc-alpha/2022-November/143265.html) | Fangrui Song                     |
| 2022-November  | [[PATCH v2 3/4] stdlib: Remove if inline asm context casts if compiler does not support it](https://sourceware.org/pipermail/libc-alpha/2022-November/143151.html) | Adhemerval Zanella               |
| 2022-November  | [[PATCH v2 4/4] Apply asm redirection in gmp.h before first use](https://sourceware.org/pipermail/libc-alpha/2022-November/143152.html) | Adhemerval Zanella               |
| 2022-November  | [[PATCH v2 4/4] Apply asm redirection in gmp.h before first use](https://sourceware.org/pipermail/libc-alpha/2022-November/143266.html) | Fangrui Song                     |
| 2022-November  | [Add restrict annotations to all functions that require it](https://sourceware.org/pipermail/libc-alpha/2022-November/143606.html) | Alejandro Colomar                |
| 2022-November  | [[PATCH v6] elf: Rework exception handling in the dynamic loader [BZ #25486]](https://sourceware.org/pipermail/libc-alpha/2022-November/143146.html) | Siddhesh Poyarekar               |
| 2022-November  | [[RFC] Supporting malloc_usable_size](https://sourceware.org/pipermail/libc-alpha/2022-November/143599.html) | Siddhesh Poyarekar               |
| 2022-November  | [Monday Patch Review for 2022-11-08](https://sourceware.org/pipermail/libc-alpha/2022-November/143347.html) | Carlos O'Donell                  |
| 2022-November  | [Monday Patch Review for 2022-11-08](https://sourceware.org/pipermail/libc-alpha/2022-November/143348.html) | Noah Goldstein                   |
| 2022-October   | [[PATCH 00/11] Initial fixes for clang build support](https://sourceware.org/pipermail/libc-alpha/2022-October/143036.html) | Adhemerval Zanella               |
| 2022-October   | [[PATCH 01/11] stdlib/longlong.h: Remove incorrect lvalue to rvalue conversion from asm output constraints](https://sourceware.org/pipermail/libc-alpha/2022-October/143037.html) | Adhemerval Zanella               |
| 2022-October   | [[PATCH 03/11] Rewrite find_cxx_header config configure.ac](https://sourceware.org/pipermail/libc-alpha/2022-October/143039.html) | Adhemerval Zanella               |
| 2022-October   | [[PATCH 02/11] Disable __USE_EXTERN_INLINES for clang](https://sourceware.org/pipermail/libc-alpha/2022-October/143038.html) | Adhemerval Zanella               |
| 2022-October   | [[PATCH 01/11] stdlib/longlong.h: Remove incorrect lvalue to rvalue conversion from asm output constraints](https://sourceware.org/pipermail/libc-alpha/2022-October/143052.html) | Fangrui Song                     |
| 2022-October   | [[PATCH 06/11] Disable use of -fsignaling-nans if compiler does not support it](https://sourceware.org/pipermail/libc-alpha/2022-October/143063.html) | Fangrui Song                     |
| 2022-October   | [[PATCH 02/11] Disable __USE_EXTERN_INLINES for clang](https://sourceware.org/pipermail/libc-alpha/2022-October/143101.html) | Adhemerval Zanella Netto         |
| 2022-October   | [[PATCH 03/11] Rewrite find_cxx_header config configure.ac](https://sourceware.org/pipermail/libc-alpha/2022-October/143062.html) | Fangrui Song                     |
| 2022-October   | [[PATCH 03/11] Rewrite find_cxx_header config configure.ac](https://sourceware.org/pipermail/libc-alpha/2022-October/143103.html) | Adhemerval Zanella Netto         |
| 2022-October   | [[PATCH 05/11] intl: Fix clang -Wunused-but-set-variable on plural.c](https://sourceware.org/pipermail/libc-alpha/2022-October/143060.html) | Fangrui Song                     |
| 2022-October   | [[PATCH 02/11] Disable __USE_EXTERN_INLINES for clang](https://sourceware.org/pipermail/libc-alpha/2022-October/143054.html) | Fangrui Song                     |
| 2022-October   | [[PATCH 01/11] stdlib/longlong.h: Remove incorrect lvalue to rvalue conversion from asm output constraints](https://sourceware.org/pipermail/libc-alpha/2022-October/143100.html) | Adhemerval Zanella Netto         |
| 2022-October   | [[PATCH 04/11] linux: Move hidden_proto before static inline usage on not-cancel.h](https://sourceware.org/pipermail/libc-alpha/2022-October/143064.html) | Fangrui Song                     |
| 2022-October   | [[PATCH 04/11] linux: Move hidden_proto before static inline usage on not-cancel.h](https://sourceware.org/pipermail/libc-alpha/2022-October/143040.html) | Adhemerval Zanella               |
| 2022-October   | [[PATCH 02/11] Disable __USE_EXTERN_INLINES for clang](https://sourceware.org/pipermail/libc-alpha/2022-October/143051.html) | Joseph Myers                     |
| 2022-October   | [[PATCH 08/11] configure: Use -Wno-ignored-attributes if compiler warns about multiple aliases](https://sourceware.org/pipermail/libc-alpha/2022-October/143045.html) | Adhemerval Zanella               |
| 2022-October   | [[PATCH 04/11] linux: Move hidden_proto before static inline usage on not-cancel.h](https://sourceware.org/pipermail/libc-alpha/2022-October/143104.html) | Adhemerval Zanella Netto         |
| 2022-October   | [[PATCH 08/11] configure: Use -Wno-ignored-attributes if compiler warns about multiple aliases](https://sourceware.org/pipermail/libc-alpha/2022-October/143111.html) | Fangrui Song                     |
| 2022-October   | [[PATCH 08/11] configure: Use -Wno-ignored-attributes if compiler warns about multiple aliases](https://sourceware.org/pipermail/libc-alpha/2022-October/143107.html) | Adhemerval Zanella Netto         |
| 2022-October   | [[PATCH 06/11] Disable use of -fsignaling-nans if compiler does not support it](https://sourceware.org/pipermail/libc-alpha/2022-October/143108.html) | Fangrui Song                     |
| 2022-October   | [[PATCH 07/11] stdlib: Move attribute_hidden definition to function prototype at gmp.h](https://sourceware.org/pipermail/libc-alpha/2022-October/143065.html) | Fangrui Song                     |
| 2022-October   | [[PATCH 09/11] alloc_buffer: Apply asm redirection before first use](https://sourceware.org/pipermail/libc-alpha/2022-October/143058.html) | Fangrui Song                     |
| 2022-October   | [[PATCH 07/11] stdlib: Move attribute_hidden definition to function prototype at gmp.h](https://sourceware.org/pipermail/libc-alpha/2022-October/143106.html) | Adhemerval Zanella Netto         |
| 2022-October   | [[PATCH 07/11] stdlib: Move attribute_hidden definition to function prototype at gmp.h](https://sourceware.org/pipermail/libc-alpha/2022-October/143043.html) | Adhemerval Zanella               |
| 2022-October   | [[PATCH 05/11] intl: Fix clang -Wunused-but-set-variable on plural.c](https://sourceware.org/pipermail/libc-alpha/2022-October/143105.html) | Adhemerval Zanella Netto         |
| 2022-October   | [[PATCH 09/11] alloc_buffer: Apply asm redirection before first use](https://sourceware.org/pipermail/libc-alpha/2022-October/143044.html) | Adhemerval Zanella               |
| 2022-October   | [[PATCH 05/11] intl: Fix clang -Wunused-but-set-variable on plural.c](https://sourceware.org/pipermail/libc-alpha/2022-October/143041.html) | Adhemerval Zanella               |
| 2022-October   | [[PATCH 08/11] configure: Use -Wno-ignored-attributes if compiler warns about multiple aliases](https://sourceware.org/pipermail/libc-alpha/2022-October/143068.html) | Fangrui Song                     |
| 2022-October   | [[PATCH 06/11] Disable use of -fsignaling-nans if compiler does not support it](https://sourceware.org/pipermail/libc-alpha/2022-October/143042.html) | Adhemerval Zanella               |
| 2022-October   | [[PATCH 09/11] alloc_buffer: Apply asm redirection before first use](https://sourceware.org/pipermail/libc-alpha/2022-October/143109.html) | Adhemerval Zanella Netto         |
| 2022-October   | [[PATCH 10/11] allocate_once: Apply asm redirection before first use](https://sourceware.org/pipermail/libc-alpha/2022-October/143046.html) | Adhemerval Zanella               |
| 2022-October   | [[PATCH 10/11] allocate_once: Apply asm redirection before first use](https://sourceware.org/pipermail/libc-alpha/2022-October/143059.html) | Fangrui Song                     |
| 2022-October   | [[PATCH 11/11] nptl: Fix pthread_create.c build with clang](https://sourceware.org/pipermail/libc-alpha/2022-October/143066.html) | Fangrui Song                     |
| 2022-October   | [[PATCH 11/11] nptl: Fix pthread_create.c build with clang](https://sourceware.org/pipermail/libc-alpha/2022-October/143110.html) | Adhemerval Zanella Netto         |
| 2022-October   | [[PATCH 11/11] nptl: Fix pthread_create.c build with clang](https://sourceware.org/pipermail/libc-alpha/2022-October/143047.html) | Adhemerval Zanella               |
| 2022-October   | [[PATCH] time: Skip overflow itimer tests on 32-bit systems](https://sourceware.org/pipermail/libc-alpha/2022-October/143048.html) | Aurelien Jarno                   |
| 2022-October   | [[PATCH] x86: Remove .tfloat usage](https://sourceware.org/pipermail/libc-alpha/2022-October/142430.html) | Adhemerval Zanella Netto         |
| 2022-October   | [[PATCH v2] linux: Avoid shifting a negative signed on POSIX timer interface](https://sourceware.org/pipermail/libc-alpha/2022-October/142850.html) | Adhemerval Zanella Netto         |
| 2022-October   | [[PATCH v2] x86: Remove .tfloat usage](https://sourceware.org/pipermail/libc-alpha/2022-October/142476.html) | Fangrui Song                     |
| 2022-October   | [[PATCH v2] x86: Remove .tfloat usage](https://sourceware.org/pipermail/libc-alpha/2022-October/142431.html) | Adhemerval Zanella               |
| 2022-October   | [More efficient fmod()](https://sourceware.org/pipermail/libc-alpha/2022-October/142399.html) | Adhemerval Zanella Netto         |
| 2022-October   | [More efficient fmod()](https://sourceware.org/pipermail/libc-alpha/2022-October/142408.html) | Oliver Schädlich                 |
| 2022-October   | [The GNU Toolchain Infrastructure Project](https://sourceware.org/pipermail/libc-alpha/2022-October/142487.html) | Frank Ch. Eigler                 |
| 2022-October   | [Stepping down as powerpc machine maintainer](https://sourceware.org/pipermail/libc-alpha/2022-October/143031.html) | Tulio Magno Quites Machado Filho |
| 2022-October   | [The GNU Toolchain Infrastructure Project](https://sourceware.org/pipermail/libc-alpha/2022-October/142485.html) | Frank Ch. Eigler                 |
| 2022-October   | [The GNU Toolchain Infrastructure Project](https://sourceware.org/pipermail/libc-alpha/2022-October/142486.html) | Siddhesh Poyarekar               |
| 2022-October   | [The GNU Toolchain Infrastructure Project](https://sourceware.org/pipermail/libc-alpha/2022-October/142484.html) | Siddhesh Poyarekar               |
| 2022-September | [[RESEND PATCH] Makeconfig: Set pie-ccflag to -fPIE by default](https://sourceware.org/pipermail/libc-alpha/2022-September/142135.html) | Fangrui Song                     |
| 2022-September | [[PATCH] x86: Remove .tfloat usage](https://sourceware.org/pipermail/libc-alpha/2022-September/142232.html) | Adhemerval Zanella               |
| 2022-September | [[PATCH] x86: Remove .tfloat usage](https://sourceware.org/pipermail/libc-alpha/2022-September/142236.html) | Fangrui Song                     |
| 2022-September | [[PATCH] x86: Remove .tfloat usage](https://sourceware.org/pipermail/libc-alpha/2022-September/142237.html) | Fangrui Song                     |
| 2022-September | [[PATCH] x86: Remove .tfloat usage](https://sourceware.org/pipermail/libc-alpha/2022-September/142252.html) | H.J. Lu                          |
| 2022-September | [[PATCH] x86: Remove .tfloat usage](https://sourceware.org/pipermail/libc-alpha/2022-September/142251.html) | H.J. Lu                          |
| 2022-September | [[PATCH] x86: Remove .tfloat usage](https://sourceware.org/pipermail/libc-alpha/2022-September/142235.html) | Noah Goldstein                   |
| 2022-August    | [[PATCH] LoongArch: Fix dl-machine.h code formatting](https://sourceware.org/pipermail/libc-alpha/2022-August/141538.html) | Xi Ruoyao                        |
| 2022-August    | [[PATCH] LoongArch: Fix dl-machine.h code formatting](https://sourceware.org/pipermail/libc-alpha/2022-August/141539.html) | Xi Ruoyao                        |
| 2022-August    | [[PATCH] nptl: x86_64: Use same code for CURRENT_STACK_FRAME and stackinfo_get_sp](https://sourceware.org/pipermail/libc-alpha/2022-August/141769.html) | Adhemerval Zanella               |
| 2022-August    | [[PATCH] nptl: x86_64: Use same code for CURRENT_STACK_FRAME and stackinfo_get_sp](https://sourceware.org/pipermail/libc-alpha/2022-August/141787.html) | Noah Goldstein                   |
| 2022-August    | [[PATCH] nptl: x86_64: Use stackinfo.h definition for CURRENT_STACK_FRAME](https://sourceware.org/pipermail/libc-alpha/2022-August/141742.html) | Noah Goldstein                   |
| 2022-August    | [[PATCH] nptl: x86_64: Use stackinfo.h definition for CURRENT_STACK_FRAME](https://sourceware.org/pipermail/libc-alpha/2022-August/141752.html) | Adhemerval Zanella Netto         |
| 2022-August    | [[PATCH] nptl: x86_64: Use same code for CURRENT_STACK_FRAME and stackinfo_get_sp](https://sourceware.org/pipermail/libc-alpha/2022-August/141789.html) | Noah Goldstein                   |
| 2022-August    | [[PATCH] nptl: x86_64: Use same code for CURRENT_STACK_FRAME and stackinfo_get_sp](https://sourceware.org/pipermail/libc-alpha/2022-August/141788.html) | Adhemerval Zanella Netto         |
| 2022-August    | [[PATCH] nptl: x86_64: Use stackinfo.h definition for CURRENT_STACK_FRAME](https://sourceware.org/pipermail/libc-alpha/2022-August/141736.html) | Adhemerval Zanella               |
| 2022-August    | [[PATCH resend] LoongArch: Fix dl-machine.h code formatting](https://sourceware.org/pipermail/libc-alpha/2022-August/141541.html) | Xi Ruoyao                        |
| 2022-August    | [Should we make DT_HASH dynamic section for glibc?](https://sourceware.org/pipermail/libc-alpha/2022-August/141311.html) | Fangrui Song                     |
| 2022-August    | [Should we make DT_HASH dynamic section for glibc?](https://sourceware.org/pipermail/libc-alpha/2022-August/141312.html) | Sam James                        |
| 2022-July      | [[PATCHv3] Apply asm redirections in stdio.h before first use [BZ #27087]](https://sourceware.org/pipermail/libc-alpha/2022-July/140499.html) | Paul E Murphy                    |
| 2022-July      | [[PATCHv3] Apply asm redirections in stdio.h before first use [BZ #27087]](https://sourceware.org/pipermail/libc-alpha/2022-July/140431.html) | Tulio Magno Quites Machado Filho |
| 2022-July      | [[PATCHv3] Apply asm redirections in stdio.h before first use [BZ #27087]](https://sourceware.org/pipermail/libc-alpha/2022-July/140538.html) | Carlos O'Donell                  |
| 2022-July      | [[PATCH v4 2/3] stdlib: Implement mbrtoc8(), c8rtomb(), and the char8_t typedef.](https://sourceware.org/pipermail/libc-alpha/2022-July/140926.html) | Tom Honermann                    |
| 2022-July      | [[PATCH v4 2/3] stdlib: Implement mbrtoc8(), c8rtomb(), and the char8_t typedef.](https://sourceware.org/pipermail/libc-alpha/2022-July/140928.html) | Adhemerval Zanella Netto         |
| 2022-July      | [Monday Patch Queue Review update (2022-07-11)](https://sourceware.org/pipermail/libc-alpha/2022-July/140486.html) | Carlos O'Donell                  |
| 2022-June      | [[patch/idea] Add register scrambling to testsuite](https://sourceware.org/pipermail/libc-alpha/2022-June/139777.html) | Fangrui Song                     |
| 2022-June      | [[PATCH v2 1/4] misc: Optimize internal usage of __libc_single_threaded](https://sourceware.org/pipermail/libc-alpha/2022-June/139820.html) | Fangrui Song                     |
| 2022-June      | [[PATCHv2] Apply asm redirections in stdio.h before first use [BZ #27087]](https://sourceware.org/pipermail/libc-alpha/2022-June/140313.html) | Tulio Magno Quites Machado Filho |
| 2022-June      | [[PATCH v2] elf: Refine direct extern access diagnostics to protected symbol](https://sourceware.org/pipermail/libc-alpha/2022-June/139732.html) | Fangrui Song                     |
| 2022-June      | [[PATCH v2] elf: Refine direct extern access diagnostics to protected symbol](https://sourceware.org/pipermail/libc-alpha/2022-June/139693.html) | Fangrui Song                     |
| 2022-June      | [[PATCH v2] elf: Refine direct extern access diagnostics to protected symbol](https://sourceware.org/pipermail/libc-alpha/2022-June/139685.html) | Fangrui Song                     |
| 2022-May       | [[PATCH 1/1] x86_64: Add strstr function with 512-bit EVEX](https://sourceware.org/pipermail/libc-alpha/2022-May/139115.html) | Noah Goldstein                   |
| 2022-May       | [[PATCH 1/2] benchtests: Add wcrtomb microbenchmark](https://sourceware.org/pipermail/libc-alpha/2022-May/138528.html) | Siddhesh Poyarekar               |
| 2022-May       | [[PATCH 1/2] benchtests: Add wcrtomb microbenchmark](https://sourceware.org/pipermail/libc-alpha/2022-May/138527.html) | Siddhesh Poyarekar               |
| 2022-May       | [[PATCH 1/2] benchtests: Add wcrtomb microbenchmark](https://sourceware.org/pipermail/libc-alpha/2022-May/138526.html) | Adhemerval Zanella               |
| 2022-May       | [[PATCH 1/1] x86_64: Add strstr function with 512-bit EVEX](https://sourceware.org/pipermail/libc-alpha/2022-May/139132.html) | Devulapalli, Raghuveer           |
| 2022-May       | [[PATCH 1/2] benchtests: Add wcrtomb microbenchmark](https://sourceware.org/pipermail/libc-alpha/2022-May/138531.html) | Adhemerval Zanella               |
| 2022-May       | [[PATCH 2/2] nss: handle stat failure in check_reload_and_get (BZ #28752)](https://sourceware.org/pipermail/libc-alpha/2022-May/139130.html) | Adhemerval Zanella               |
| 2022-May       | [[PATCH 2/3] Revert "[AArch64][BZ #17711] Fix extern protected data handling"](https://sourceware.org/pipermail/libc-alpha/2022-May/139179.html) | Fangrui Song                     |
| 2022-May       | [[PATCH] Check for ISO C compilers should also allow C++](https://sourceware.org/pipermail/libc-alpha/2022-May/138756.html) | Fangrui Song                     |
| 2022-May       | [[PATCH] Change fno-unit-at-a-time to fno-toplevel-reorder](https://sourceware.org/pipermail/libc-alpha/2022-May/138644.html) | Fangrui Song                     |
| 2022-May       | [[PATCH] Check for ISO C compilers should also allow C++](https://sourceware.org/pipermail/libc-alpha/2022-May/138739.html) | Florian Weimer                   |
| 2022-May       | [[PATCH] Check for ISO C compilers should also allow C++](https://sourceware.org/pipermail/libc-alpha/2022-May/138741.html) | Jonathan Wakely                  |
| 2022-May       | [[PATCH] Check for ISO C compilers should also allow C++](https://sourceware.org/pipermail/libc-alpha/2022-May/138781.html) | Jonathan Wakely                  |
| 2022-May       | [[PATCH] Check for ISO C compilers should also allow C++](https://sourceware.org/pipermail/libc-alpha/2022-May/138738.html) | Jonathan Wakely                  |
| 2022-May       | [[PATCH] elf: Remove ELF_RTYPE_CLASS_EXTERN_PROTECTED_DATA](https://sourceware.org/pipermail/libc-alpha/2022-May/139178.html) | Fangrui Song                     |
| 2022-May       | [[PATCH] Check for ISO C compilers should also allow C++](https://sourceware.org/pipermail/libc-alpha/2022-May/138740.html) | Joseph Myers                     |
| 2022-May       | [[PATCH] elf: Remove ELF_RTYPE_CLASS_EXTERN_PROTECTED_DATA](https://sourceware.org/pipermail/libc-alpha/2022-May/139183.html) | Szabolcs Nagy                    |
| 2022-May       | [[PATCH] elf: Remove fallback to the start of DT_STRTAB for dladdr](https://sourceware.org/pipermail/libc-alpha/2022-May/138315.html) | Fangrui Song                     |
| 2022-May       | [[PATCH] elf: Remove fallback to the start of DT_STRTAB for dladdr](https://sourceware.org/pipermail/libc-alpha/2022-May/138317.html) | Fangrui Song                     |
| 2022-May       | [[PATCH] Change fno-unit-at-a-time to fno-toplevel-reorder](https://sourceware.org/pipermail/libc-alpha/2022-May/138458.html) | Adhemerval Zanella               |
| 2022-May       | [[PATCH] elf: Remove fallback to the start of DT_STRTAB for dladdr](https://sourceware.org/pipermail/libc-alpha/2022-May/138316.html) | Florian Weimer                   |
| 2022-May       | [[PATCH] string.h: fix __fortified_attr_access macro call [BZ #29162]](https://sourceware.org/pipermail/libc-alpha/2022-May/138975.html) | Siddhesh Poyarekar               |
| 2022-May       | [[PATCH] string.h: fix __fortified_attr_access macro call [BZ #29162]](https://sourceware.org/pipermail/libc-alpha/2022-May/138973.html) | Siddhesh Poyarekar               |
| 2022-May       | [[PATCH] string.h: fix __fortified_attr_access macro call [BZ #29162]](https://sourceware.org/pipermail/libc-alpha/2022-May/138981.html) | Sergei Trofimovich               |
| 2022-May       | [[PATCH] x86_64: Remove bzero optimization](https://sourceware.org/pipermail/libc-alpha/2022-May/138755.html) | H.J. Lu                          |
| 2022-May       | [[PATCH] x86_64: Remove bzero optimization](https://sourceware.org/pipermail/libc-alpha/2022-May/138754.html) | Noah Goldstein                   |
| 2022-May       | [[PATCH v2 1/4] Add declare_object_symbol_alias for assembly codes (BZ #28128)](https://sourceware.org/pipermail/libc-alpha/2022-May/138671.html) | Fangrui Song                     |
| 2022-May       | [[PATCH v3] elf: Rewrite long RESOLVE_MAP macro to a debug friendly function](https://sourceware.org/pipermail/libc-alpha/2022-May/138984.html) | Adhemerval Zanella               |
| 2022-May       | [[PATCH v3] elf: Rewrite long RESOLVE_MAP macro to a debug friendly function](https://sourceware.org/pipermail/libc-alpha/2022-May/138985.html) | Siddhesh Poyarekar               |
| 2022-May       | [[PATCH v3] elf: Rewrite long RESOLVE_MAP macro to a debug friendly function](https://sourceware.org/pipermail/libc-alpha/2022-May/139009.html) | Adhemerval Zanella               |
| 2022-April     | [[PATCH 4/7] x86: Add SSSE3 optimized chacha20](https://sourceware.org/pipermail/libc-alpha/2022-April/137829.html) | Noah Goldstein                   |
| 2022-April     | [[PATCH 4/7] x86: Add SSSE3 optimized chacha20](https://sourceware.org/pipermail/libc-alpha/2022-April/137827.html) | Adhemerval Zanella               |
| 2022-April     | [[PATCH 4/7] x86: Add SSSE3 optimized chacha20](https://sourceware.org/pipermail/libc-alpha/2022-April/137823.html) | Adhemerval Zanella               |
| 2022-April     | [[PATCH 4/7] x86: Add SSSE3 optimized chacha20](https://sourceware.org/pipermail/libc-alpha/2022-April/137839.html) | Adhemerval Zanella               |
| 2022-April     | [[PATCH] math: Add math-use-builtins-fabs](https://sourceware.org/pipermail/libc-alpha/2022-April/137597.html) | Joseph Myers                     |
| 2022-April     | [[PATCH] math: Add math-use-builtins-fabs](https://sourceware.org/pipermail/libc-alpha/2022-April/137591.html) | Adhemerval Zanella               |
| 2022-April     | [[PATCH 4/7] x86: Add SSSE3 optimized chacha20](https://sourceware.org/pipermail/libc-alpha/2022-April/137824.html) | Noah Goldstein                   |
| 2022-April     | [[PATCH] math: Add math-use-builtins-fabs](https://sourceware.org/pipermail/libc-alpha/2022-April/137580.html) | Joseph Myers                     |
| 2022-April     | [[PATCH] math: Add math-use-builtins-fabs](https://sourceware.org/pipermail/libc-alpha/2022-April/137583.html) | Adhemerval Zanella               |
| 2022-April     | [[PATCH] math: Add math-use-builtins-fabs](https://sourceware.org/pipermail/libc-alpha/2022-April/137579.html) | Adhemerval Zanella               |
| 2022-April     | [[PATCH] math: Add math-use-builtins-fabs](https://sourceware.org/pipermail/libc-alpha/2022-April/137601.html) | Adhemerval Zanella               |
| 2022-April     | [[PATCH] Remove fno-unit-at-a-time make variable](https://sourceware.org/pipermail/libc-alpha/2022-April/137609.html) | Florian Weimer                   |
| 2022-April     | [[PATCH] Remove fno-unit-at-a-time make variable](https://sourceware.org/pipermail/libc-alpha/2022-April/137605.html) | Florian Weimer                   |
| 2022-April     | [[PATCH] Remove fno-unit-at-a-time make variable](https://sourceware.org/pipermail/libc-alpha/2022-April/137603.html) | Adhemerval Zanella               |
| 2022-April     | [[PATCH] Remove fno-unit-at-a-time make variable](https://sourceware.org/pipermail/libc-alpha/2022-April/137608.html) | Adhemerval Zanella               |
| 2022-April     | [[PATCH] Remove fno-unit-at-a-time make variable](https://sourceware.org/pipermail/libc-alpha/2022-April/137613.html) | Adhemerval Zanella               |
| 2022-April     | [[PATCH] Remove fno-unit-at-a-time make variable](https://sourceware.org/pipermail/libc-alpha/2022-April/137611.html) | Adhemerval Zanella               |
| 2022-April     | [[PATCH] Remove fno-unit-at-a-time make variable](https://sourceware.org/pipermail/libc-alpha/2022-April/137612.html) | Florian Weimer                   |
| 2022-April     | [[PATCH] Remove fno-unit-at-a-time make variable](https://sourceware.org/pipermail/libc-alpha/2022-April/137627.html) | Fāng-ruì Sòng                    |
| 2022-April     | [[PATCH] Remove fno-unit-at-a-time make variable](https://sourceware.org/pipermail/libc-alpha/2022-April/137620.html) | Adhemerval Zanella               |
| 2022-April     | [[PATCH v2] benchtests: Add pthread-mutex-locks bench](https://sourceware.org/pipermail/libc-alpha/2022-April/138048.html) | Guo, Wangyang                    |
| 2022-April     | [[PATCH v2] benchtests: Add pthread-mutex-locks bench](https://sourceware.org/pipermail/libc-alpha/2022-April/138120.html) | Noah Goldstein                   |
| 2022-April     | [[PATCH v2] benchtests: Add pthread-mutex-locks bench](https://sourceware.org/pipermail/libc-alpha/2022-April/138238.html) | H.J. Lu                          |
| 2022-April     | [[PATCH v2] benchtests: Add pthread-mutex-locks bench](https://sourceware.org/pipermail/libc-alpha/2022-April/138027.html) | Noah Goldstein                   |
| 2022-April     | [[PATCH v3 2/2] Default to --with-default-link=no (bug 25812)](https://sourceware.org/pipermail/libc-alpha/2022-April/138278.html) | Fangrui Song                     |
| 2022-April     | [[PATCH v3 2/2] Default to --with-default-link=no (bug 25812)](https://sourceware.org/pipermail/libc-alpha/2022-April/138260.html) | Fangrui Song                     |
| 2022-April     | [[PATCH v3 2/2] Default to --with-default-link=no (bug 25812)](https://sourceware.org/pipermail/libc-alpha/2022-April/138261.html) | Florian Weimer                   |
| 2022-April     | [[PATCH v5] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-April/137548.html) | Noah Goldstein                   |
| 2022-April     | [[PATCH v5] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-April/137537.html) | Carlos O'Donell                  |
| 2022-April     | [[patch v6] Allow for unpriviledged nested containers](https://sourceware.org/pipermail/libc-alpha/2022-April/137538.html) | Carlos O'Donell                  |
| 2022-April     | [[PATCH v6] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-April/137702.html) | Noah Goldstein                   |
| 2022-April     | [[PATCH v6] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-April/137691.html) | Carlos O'Donell                  |
| 2022-April     | [[PATCH v6] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-April/137547.html) | Noah Goldstein                   |
| 2022-April     | [[PATCH v7 3/6] elf: Support DT_RELR relative relocation format [BZ #27924]](https://sourceware.org/pipermail/libc-alpha/2022-April/137549.html) | Adhemerval Zanella               |
| 2022-April     | [Monday Patch Queue Review update (2022-04-04)](https://sourceware.org/pipermail/libc-alpha/2022-April/137536.html) | Carlos O'Donell                  |
| 2022-April     | [Monday Patch Queue Review update (2022-04-11)](https://sourceware.org/pipermail/libc-alpha/2022-April/137929.html) | Carlos O'Donell                  |
| 2022-March     | [[PATCH] stdio: Move include of bits/stdio-ldbl.h before bits/stdio.h](https://sourceware.org/pipermail/libc-alpha/2022-March/136791.html) | Adhemerval Zanella               |
| 2022-March     | [[PATCH v1 1/2] random-bits: Factor out entropy generating function](https://sourceware.org/pipermail/libc-alpha/2022-March/137364.html) | Noah Goldstein                   |
| 2022-March     | [[PATCH v2] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137438.html) | Fangrui Song                     |
| 2022-March     | [[PATCH v2] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137451.html) | Noah Goldstein                   |
| 2022-March     | [[PATCH v2] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137452.html) | Joseph Myers                     |
| 2022-March     | [[PATCH v2] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137432.html) | Noah Goldstein                   |
| 2022-March     | [[PATCH v2] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137444.html) | Joseph Myers                     |
| 2022-March     | [[PATCH v2] nptl: Add backoff mechanism to spinlock loop](https://sourceware.org/pipermail/libc-alpha/2022-March/137435.html) | Adhemerval Zanella               |
| 2022-March     | [[PATCH v2] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137441.html) | Noah Goldstein                   |
| 2022-March     | [[PATCH v2] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137456.html) | Andreas Schwab                   |
| 2022-March     | [[PATCH v1] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137411.html) | Fangrui Song                     |
| 2022-March     | [[PATCH v1] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137412.html) | Noah Goldstein                   |
| 2022-March     | [[PATCH v2] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137449.html) | Noah Goldstein                   |
| 2022-March     | [[PATCH v1] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137362.html) | Noah Goldstein                   |
| 2022-March     | [[PATCH v3] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137445.html) | Fangrui Song                     |
| 2022-March     | [[PATCH v3] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137447.html) | Noah Goldstein                   |
| 2022-March     | [[PATCH v4] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137448.html) | Noah Goldstein                   |
| 2022-March     | [[PATCH v3] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137446.html) | Florian Weimer                   |
| 2022-March     | [[PATCH v3] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137453.html) | Noah Goldstein                   |
| 2022-March     | [[PATCH v6 3/5] Add GLIBC_ABI_DT_RELR for DT_RELR support](https://sourceware.org/pipermail/libc-alpha/2022-March/137436.html) | H.J. Lu                          |
| 2022-March     | [[PATCH v4 3/5] Add GLIBC_ABI_DT_RELR for DT_RELR support](https://sourceware.org/pipermail/libc-alpha/2022-March/136773.html) | Peter O'Connor                   |
| 2022-March     | [[PATCH v6 3/5] Add GLIBC_ABI_DT_RELR for DT_RELR support](https://sourceware.org/pipermail/libc-alpha/2022-March/137434.html) | Adhemerval Zanella               |
| 2022-March     | [[PATCH v5] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137454.html) | Noah Goldstein                   |
| 2022-March     | [[PATCH v6 3/5] Add GLIBC_ABI_DT_RELR for DT_RELR support](https://sourceware.org/pipermail/libc-alpha/2022-March/137437.html) | Adhemerval Zanella               |
| 2022-March     | [Monday Patch Queue Review update (2022-03-28)](https://sourceware.org/pipermail/libc-alpha/2022-March/137396.html) | Carlos O'Donell                  |
| 2022-March     | [Monday Patch Queue Review update (2022-03-28)](https://sourceware.org/pipermail/libc-alpha/2022-March/137403.html) | Fangrui Song                     |
| 2022-March     | [Monday Patch Queue Review update (2022-03-07)](https://sourceware.org/pipermail/libc-alpha/2022-March/136955.html) | Carlos O'Donell                  |
| 2022-March     | [[PATCH v3] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137450.html) | Florian Weimer                   |
| 2022-March     | [[PATCH v3] Add .clang-format style file](https://sourceware.org/pipermail/libc-alpha/2022-March/137440.html) | Noah Goldstein                   |
| 2022-February  | [[PATCH] stdio: Move include of bits/stdio-ldbl.h before bits/stdio.h](https://sourceware.org/pipermail/libc-alpha/2022-February/136681.html) | Adhemerval Zanella               |
| 2022-January   | [[PATCH 0/10] ld: Implement DT_RELR for x86](https://sourceware.org/pipermail/libc-alpha/2022-January/135066.html) | H.J. Lu                          |
| 2022-January   | [[PATCH 0/10] ld: Implement DT_RELR for x86](https://sourceware.org/pipermail/libc-alpha/2022-January/135065.html) | Fangrui Song                     |
| 2022-January   | [[PATCH 0/10] ld: Implement DT_RELR for x86](https://sourceware.org/pipermail/libc-alpha/2022-January/135080.html) | H.J. Lu                          |
| 2022-January   | [[PATCH 2/2] debug: Synchronize feature guards in fortified functions [BZ #28746]](https://sourceware.org/pipermail/libc-alpha/2022-January/134989.html) | Siddhesh Poyarekar               |
| 2022-January   | [[PATCH v2 0/9] ld: Implement DT_RELR for x86](https://sourceware.org/pipermail/libc-alpha/2022-January/135095.html) | Fangrui Song                     |
| 2022-January   | [[PATCH v2 2/2] debug: Synchronize feature guards in fortified functions [BZ #28746]](https://sourceware.org/pipermail/libc-alpha/2022-January/134995.html) | Siddhesh Poyarekar               |
| 2022-January   | [[PATCH v2 2/2] debug: Synchronize feature guards in fortified functions [BZ #28746]](https://sourceware.org/pipermail/libc-alpha/2022-January/135033.html) | Siddhesh Poyarekar               |
| 2022-January   | [[PATCH v2 2/2] debug: Synchronize feature guards in fortified functions [BZ #28746]](https://sourceware.org/pipermail/libc-alpha/2022-January/135026.html) | Adhemerval Zanella               |
| 2022-January   | [[PATCH v2 2/2] debug: Synchronize feature guards in fortified functions [BZ #28746]](https://sourceware.org/pipermail/libc-alpha/2022-January/135040.html) | Adhemerval Zanella               |
| 2022-January   | [[PATCH v3 2/2] debug: Synchronize feature guards in fortified functions [BZ #28746]](https://sourceware.org/pipermail/libc-alpha/2022-January/135141.html) | Siddhesh Poyarekar               |
| 2022-January   | [[PATCH v4 2/2] debug: Synchronize feature guards in fortified functions [BZ #28746]](https://sourceware.org/pipermail/libc-alpha/2022-January/135146.html) | Siddhesh Poyarekar               |
| 2022-January   | [[PATCH v5 2/2] debug: Synchronize feature guards in fortified functions [BZ #28746]](https://sourceware.org/pipermail/libc-alpha/2022-January/135196.html) | Siddhesh Poyarekar               |
| 2022-January   | [[PATCH v5 2/2] debug: Synchronize feature guards in fortified functions [BZ #28746]](https://sourceware.org/pipermail/libc-alpha/2022-January/135207.html) | Adhemerval Zanella               |
| 2022-January   | [Initial DT_RELR support in bfd linker](https://sourceware.org/pipermail/libc-alpha/2022-January/134992.html) | Fangrui Song                     |

## 附录——clang 编译 glibc 操作教程

- 下载 glibc 源代码，配置生成 Makefile

```bash
git clone git://sourceware.org/git/glibc.git
cd glibc
git checkout glibc-2.36
mkdir build
cd build
mkdir install
export glibc_install="$(pwd)/install"
../configure --prefix "$glibc_install"
```

- 修改 glibc/scripts/glibcextract.py 文件

```c
cmd = ('%s -S -o %s -x c - < %s' % (cc, s_file_name, c_file_name))
subprocess.check_call(cmd, shell=True)
```

将上面的代码改成下面的样子，将字符串 "/opt/rh/devtoolset-9/root/usr/bin/gcc"，更改成你系统当中 gcc 编译器的路径。

```c
cmd = ('%s -S -o %s -x c - < %s' % (cc, s_file_name, c_file_name))
new_command = "/opt/rh/devtoolset-9/root/usr/bin/gcc" + cmd[3:]
subprocess.check_call(new_command, shell=True)
```

使用软连接，将生成一个名为 gcc 的软链接，链接到真实的 clang 编译器，将软连接得到的 gcc 所在的目录加入到系统环境变量当中，并且使其生效。

- 在 build 目录下面创建一个 python 脚本内容如下所示：

```python

import subprocess
import sys


def find_obj_file(command):

    start = command.index(" -o ")
    if start == -1:
        print("Not found object file")
    else:
        start += 4
        # skip space
        while True:
            c = command[start]
            if c != ' ':
                break
            start += 1
        obj_name = ""
        while True:
            c = command[start]
            if c == ' ':
                break
            obj_name += c
            start += 1
        return obj_name


if __name__ == '__main__':
    log = open("log", "a+")
    cnt = 1
    counter = "/root/tmp/number" # 要保证这个文件存在, 文件内容初始化成数字 0
    err_dir = "/root/tmp/errlog/"
    out_dir = "/root/tmp/out/"
    while True:
        # 用于保存错误编号，以便程序在因为异常情况退出时能够保存程序的执行记录
        # 执行程序之前先要保证这个文件存在
        with open(counter, "r+") as fp:
            data = int(fp.read())
            fp.seek(0)
            fp.write(str(data + 1))
        # 日志文件的保存目录
        err = err_dir + str(data) + ".errlog"
        out = out_dir + str(data) + ".outlog"
        cmd = "make 1>" + out + " 2>" + err
        subprocess.call(cmd, shell=True)

        tc = None
        with open(out, "r+") as fp:
            out_content = fp.readlines()
            for line in out_content:
                if line.startswith("gcc"):
                    filename = find_obj_file(line)
                    if not filename.endswith(".o") and not filename.endswith(".os") and not filename.endswith(".S"):
                        print("not endswith .o, exit")
                        sys.exit(0)
                    tc = "touch " + filename
                    subprocess.check_output(tc, shell=True)
        if "librtld.map.o" in out_content[-3]:
            break
        logstr = "cnt = " + str(cnt) + "\tdata = " + str(data) + "\ttc = " + tc + "\n"
        log.write(logstr)
        log.flush()
        cnt += 1
    log.close()
```

修改上面的两三个变量 `counter`、 `err_dir` 和 `out_dir` ，并且创建 counter 对应的文件，在文件当中写入一个字符 0 。 执行上面的脚本，开始编译过程。如果在执行这个 python 脚本文件时退出了，重新执行即可，直到编译完成。





