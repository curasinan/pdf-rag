Gathering material for quiz...
Generating questions...

# CS-220 Exam 2 Quiz

---

## Question 1 — Condition Flags (Recall)
*Source: L16_x86_flow_control, pages 8-11; Practice Exam 2 Key*

Suppose `%cl = 0b1111_1111` and `%al = 0b0000_0001`. After executing `add %cl, %al`, the result in `%al` is `0b0000_0000`.

Which condition flags (CF, ZF, SF, OF) are set to 1?

---

## Question 2 — Stack Frame & Calling Conventions (Conceptual Understanding)
*Source: L17_x86_Stack-1, pages 13-16; L18_x86_CallingConventions, pages 24-27; CS 220 Notes on Stack Layout*

When a function `foo` calls `bar`, list **in order** the steps that happen to the stack from the moment `foo` executes `callq bar` through the end of `bar`'s preamble. Specifically: what values are pushed, and what happens to `%rsp` and `%rbp`?

---

## Question 3 — Addressing Modes & Data Movement (Application)
*Source: L15_x86_Instructions, pages 1-17; CS220PracticeExam2, page 1*

Suppose `%rax = 0x7fffffffe750`, which points to the first element of the int array `{2, -1, 10, 12, -30}`. The following code executes:

```asm
xor  %rdx, %rdx
mov  (%rax), %edx
mov  (%rax,%rdx,4), %ecx
lea  (%rax,%rdx,4), %rsi
```

What are the final values in:
- (a) `%rdx`
- (b) `%ecx`
- (c) `%rsi`

Explain the difference between what `mov` and `lea` do in the last two instructions.

---

## Question 4 — Caller-Saved vs. Callee-Saved Registers (Comparison)
*Source: L18_x86_CallingConventions, pages 9-14, 21*

(a) Name two **callee-saved** (non-volatile) registers and two **caller-saved** (volatile) registers.

(b) If function `main` is using `%rbx` and `%r10` and is about to call `helper()`, which of those two registers does `main` need to save before the call, and which can it assume will be preserved? Why?

---

## Question 5 — Buffer Overflow Attacks (Application / Analysis)
*Source: L19_Buffer_Overflow_Attack, pages 11-30*

A function `getString()` declares `char buffer[96]` and calls `gets(buffer)`. The saved `%rbp` is immediately above the buffer, and the return address is immediately above that.

(a) How many bytes of input must an attacker provide before they begin overwriting the return address?

(b) Name **three** techniques used to prevent buffer overflow attacks, and briefly explain how each one works.

---

# Answer Key

### Q1 — CF and ZF
`0xFF + 0x01 = 0x100`, which truncates to `0x00`.
- **CF = 1**: There is a carry out of the most significant bit.
- **ZF = 1**: The 8-bit result is zero.
- SF = 0: The result's sign bit is 0.
- OF = 0: Signed interpretation: (-1) + 1 = 0, which is correct — no signed overflow.

### Q2 — Call + Preamble sequence
1. `callq bar` pushes the **return address** (address of instruction after `call`) onto the stack and jumps to `bar`. `%rsp` decreases by 8.
2. `pushq %rbp` pushes **foo's `%rbp`** onto the stack. `%rsp` decreases by 8.
3. `movq %rsp, %rbp` sets `%rbp` to the current `%rsp`, establishing the top of `bar`'s stack frame.
4. (Optionally) `subq $N, %rsp` grows the frame for local variables, and any callee-saved registers `bar` uses are pushed.

### Q3 — Addressing modes
- `xor %rdx, %rdx` zeroes `%rdx`.
- `mov (%rax), %edx` loads `array[0] = 2` into `%edx`, so **`%rdx = 2`**.
- `mov (%rax,%rdx,4), %ecx` loads from address `%rax + 2*4 = %rax+8`, which is `array[2] = 10`. **`%ecx = 10`**.
- `lea (%rax,%rdx,4), %rsi` computes the *address* `%rax + 2*4 = 0x7fffffffe758` without accessing memory. **`%rsi = 0x7fffffffe758`**.

**Key difference**: `mov` reads the *value at* the computed address; `lea` puts the *address itself* into the destination.

### Q4 — Register conventions
(a) Callee-saved: `%rbx`, `%r12`–`%r15`, `%rbp`. Caller-saved: `%rax`, `%rcx`, `%rdx`, `%rsi`, `%rdi`, `%r8`–`%r11`.

(b) `%rbx` is callee-saved — `main` can assume `helper()` will preserve it. `%r10` is caller-saved — `main` must save it before the call if it needs the value afterward.

### Q5 — Buffer overflow
(a) The buffer is 96 bytes. The saved `%rbp` is 8 bytes above that. So the attacker must write **96 + 8 = 104 bytes** before they start overwriting the return address (bytes 105–112 overwrite the return address).

(b) Three prevention techniques:
1. **Use `fgets` instead of `gets`** — `fgets` takes a size parameter and refuses to read more bytes than the buffer can hold.
2. **ASLR (Address Space Layout Randomization)** — randomizes where code is loaded in memory each run, so the attacker can't predict the address to jump to.
3. **Stack guards/canaries** (e.g., `gcc -fstack-protector`) — places a known value between the buffer and the saved `%rbp`; if the value is corrupted, the program aborts before returning.
4. *(Bonus)* **Memory protection (NX/DEP)** — stack pages are marked non-executable, so even if the attacker injects code, it can't run from the stack.
