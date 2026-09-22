/* SPDX-License-Identifier: Apache-2.0 */
/* Generic x86 coreboot payload for QEMU only. Never use on physical hardware. */

.section .text
.code32
.global _start

_start:
    /* Configure the QEMU 16550 at COM1 for 115200 8N1. */
    movw $0x3fb, %dx
    movb $0x80, %al
    outb %al, %dx
    movw $0x3f8, %dx
    movb $1, %al
    outb %al, %dx
    movw $0x3f9, %dx
    xorb %al, %al
    outb %al, %dx
    movw $0x3fb, %dx
    movb $3, %al
    outb %al, %dx
    movw $0x3fc, %dx
    outb %al, %dx

    movl $success_message, %esi
next_byte:
    lodsb
    testb %al, %al
    jz exit_qemu
    movb %al, %bl
wait_for_uart:
    movw $0x3fd, %dx
    inb %dx, %al
    testb $0x20, %al
    jz wait_for_uart
    movw $0x3f8, %dx
    movb %bl, %al
    outb %al, %dx
    jmp next_byte

exit_qemu:
    /* QEMU's explicit ISA debug-exit device maps 0x10 to process code 33. */
    movw $0xf4, %dx
    movb $0x10, %al
    outb %al, %dx
halt:
    cli
    hlt
    jmp halt

.section .rodata
success_message:
    .asciz "AMD_FW_GENERIC_QEMU_PAYLOAD_OK\r\n"
