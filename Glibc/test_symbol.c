
// compile command : gcc -c test_symbol.c
typedef unsigned long size_t;

extern void *memcpy(void *, const void *, size_t);

void *test_memcpy(void *dst, const void *src, size_t n) {
  return memcpy(dst, src, n);
}

extern void *memcpy(void *, const void *, size_t) asm("new_name_of_memcpy");
