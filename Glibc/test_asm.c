#include <linux/version.h>
#include <sys/syscall.h>
#include <bits/syscall.h>

// please use compile command "gcc -S -DX=__NR_exit demo.c -o - | grep @@@"
// this is a tricky method to extract macro value
// gcc can pass the command but clang not
#ifndef X
#define X 0
#endif // !X

int main() {
  asm ("@@@%0@@@" :: "i"((long int)(X)));
}
